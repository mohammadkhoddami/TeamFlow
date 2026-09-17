# Database 08 — Loading and N+1

## Concept

N+1 is the pattern where rendering a page of N parent objects triggers N extra
queries for related data (one per parent). SQLAlchemy solves it with loader
strategies: `joined` (same query, JOIN) and `selectin` (one extra batched query
for the whole page).

## Why it matters in async FastAPI specifically

Django's lazy loading *works* (it queries on attribute access, synchronously).
Async SQLAlchemy **cannot** lazy load — attribute access outside an await
context raises `MissingGreenlet`. So async forces you to be explicit. That's a
gift: N+1 becomes a loud error instead of a silent performance bug.

## TeamFlow's strategy table

| Relationship | Strategy | SQL produced |
| --- | --- | --- |
| `Task.assignee`, `Task.creator` | `lazy="joined"` | main SELECT gains `LEFT OUTER JOIN users` ×2 |
| `Task.labels` | `lazy="selectin"` | 1 extra query `labels JOIN task_labels WHERE task_id IN (...)` |
| `Task.watchers` | `lazy="selectin"` | 1 extra query |
| `Membership.user` | `lazy="joined"` | member list JOINs users |
| `Comment.author` | `lazy="joined"` | comment list JOINs users |

So a full task list request costs **1 (tasks) + 1 (count) + 2 (selectin
collections) = 4 queries**, regardless of page size. Serialization reads
`task.assignee`, `task.labels`, `task.watchers` — all already in memory.

## Where the eager loads are triggered

1. **Dependency fetch** — `get_task_access` uses `select(Task)`, honoring the
   strategies:

```python
task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
```

2. **List query** — `TaskRepository.list_for_org` uses `select(Task)`.
3. **Post-write refetch** — `refetch_task` with `populate_existing=True`
   (`database/03-relationships.md`).

Everything that serializes a `Task` goes through one of these three paths.

## The counter-example: `Membership.user` and freshly created rows

Newly created objects are **not** touched by loader strategies — strategies fire
on query, not construction. `MembershipRepository.add(...)` returns a fresh
`Membership` whose `.user` is unloaded; serializing it would lazy-load and
crash. The fix in `app/services/organizations.py`:

```python
membership = await membership_repo.add(Membership(user_id=user.id, ...))
await db.commit()
# Re-select so the joined-eager `user` relationship is loaded (fresh
# instances do not trigger eager strategies; implicit lazy loads are
# unsafe in async sessions).
return (await db.execute(select(Membership).where(Membership.id == membership.id))).scalar_one()
```

Same pattern in `app/services/invitations.py` (`accept_invitation`). This is the
single most common "works in tests, crashes in prod" bug for people coming from
Django: in sync Django, the lazy load just fires; in async it explodes.

## How to audit for N+1 (a review procedure)

1. Grep the serialization schema for relationship fields:
   ```bash
   grep -n "UserRead\|LabelRead" app/schemas/task.py
   ```
2. For each one, find where objects of that type are loaded and confirm the
   loader strategy or eager option is present.
3. Check every `lazy=` in `app/models/`.
4. For list endpoints, count expected queries: page query + count +
   collections. Any query count that scales with rows is a bug.

Quick empirical check: turn on `echo=True` (`DEBUG=true`) and watch the SQL log
for one task-list request — you should see the tasks SELECT, the count, and one
SELECT per selectin collection. No per-row queries.

## The other classic source: `_serialize` reading unmapped attributes

```python
# app/api/routes/tasks.py
def _serialize(task) -> TaskRead:
    read = TaskRead.model_validate(task)
    read.watcher_ids = [w.id for w in task.watchers]
    return read
```

`task.watchers` is fine **because** the access dependency/refetch guarantees
selectin loading. If a future route constructs a `Task` object by other means
(e.g., a raw `db.get(Task, id)` that misses the identity-map loader path),
this line raises `MissingGreenlet`. The safety net: that error is loud and
immediate, not a silent slowdown.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| Lazy FK access: 1 query per access (N+1) | impossible — `MissingGreenlet` |
| `select_related("assignee", "creator")` | `lazy="joined"` on the relationship |
| `prefetch_related("labels")` | `lazy="selectin"` on the collection |
| `django-debug-toolbar` query count | `echo=True` SQL log / tests asserting query counts |
| `assertNumQueries(4)` | not used; query-shape reasoning + code review |

Django's `assertNumQueries` is a great concept TeamFlow doesn't implement —
noted honestly in `mastery/10-what-i-actually-master.md`.

## Production perspective

- **Joined strategies widen the main query.** Two user joins per task row is
  fine; adding five more many-to-one relationships would bloat every page.
  When that happens, switch that relationship to `selectin` or load it via an
  explicit query for the endpoint that needs it.
- **Selectin IN-clauses** grow with page size; 100 ids per query is trivial;
  10k would need restructuring (but pagination caps at 100).
- **The count query** doesn't need joins — and doesn't get them
  (`select(func.count(Task.id))`).
- **Dashboard aggregates never load task rows** — `GROUP BY` only
  (`database/04-queries.md`). The only place rows are loaded is list/detail
  endpoints, all paginated.

## Common mistakes

1. **Serializing a freshly created/updated object without refetch** — the
   `Membership.user` trap above.
2. **`db.get(Task, id)`** for objects you will serialize — identity-map hits may
   skip eager loaders; use `select()` (why `TaskAccess` does).
3. **Adding a relationship without a strategy** — the default lazy behavior
   cannot work in async; the failure surfaces at the worst time.
4. **`joined` on collections** — row multiplication (a task with 5 labels
   appears 5 times). Collections must be `selectin` (or `subquery`).
5. **Counting queries only in dev against a tiny dataset** — N+1 is invisible
   with 3 rows; the review procedure above is dataset-independent.

## Cheat sheet

```
page query (1) + count (1) + collections (K selectin) = O(1) queries per page
many-to-one  → lazy="joined"
collection   → lazy="selectin"
fresh object → re-select before serialize (populate_existing=True)
```

## Review questions

1. How many SQL queries does `GET /organizations/{slug}/tasks?limit=20` run?
   List them.
2. Why is `lazy="joined"` wrong for `Task.labels`?
3. Why does creating a membership require a re-select before serialization?
4. Why is `MissingGreenlet` described as "a gift" compared to Django's silent
   N+1?
