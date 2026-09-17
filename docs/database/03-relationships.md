# Database 03 — Relationships

## Concept

SQLModel relationships (`Relationship()`) are SQLAlchemy ORM relationships with
Pydantic typing. They let you navigate object graphs (`task.assignee`,
`task.labels`) instead of writing joins by hand.

TeamFlow uses relationships **selectively**: one-directional, eagerly loaded,
and never manipulated as in-memory collections for M2M writes.

## The rules TeamFlow follows

1. **Declare only the direction you read.** No `back_populates` pairs.
2. **Always set an eager strategy** (`joined` for many-to-one, `selectin` for
   collections). Lazy loading raises `MissingGreenlet` in async sessions.
3. **Never assign M2M collections** (`task.labels = [...]`); write link tables
   directly and re-fetch.
4. **Two FKs to the same table need explicit `foreign_keys`.**

These four rules are the entire productive surface of relationships in async
SQLModel. Everything below is why.

## Rule 1 + 2: declared direction and eager loading

`app/models/task.py`:

```python
assignee: Optional["User"] = Relationship(
    sa_relationship_kwargs={"lazy": "joined", "foreign_keys": "Task.assignee_id"}
)
creator: Optional["User"] = Relationship(
    sa_relationship_kwargs={"lazy": "joined", "foreign_keys": "Task.created_by_id"}
)
labels: list["Label"] = Relationship(
    link_model=TaskLabelLink, sa_relationship_kwargs={"lazy": "selectin"}
)
watchers: list["User"] = Relationship(
    link_model=TaskWatcherLink, sa_relationship_kwargs={"lazy": "selectin"}
)
```

- `lazy="joined"` on many-to-one → the `SELECT` for tasks adds `LEFT OUTER JOIN
  users` — scalars ride along, zero extra queries.
- `lazy="selectin"` on collections → SQLAlchemy issues **one extra batched
  `SELECT ... WHERE task_id IN (...)`** for the whole page of tasks, not one
  per task. See `database/08-loading-and-n-plus-one.md` for the arithmetic.
- `foreign_keys="Task.assignee_id"` is mandatory: `tasks` has *two* FKs to
  `users` (`created_by_id`, `assignee_id`) and SQLAlchemy refuses to guess.

⚠️ `Optional["User"]`, not `"User | None"`. SQLModel resolves the annotation
string to find the target class; a union string like `"User | None"` fails with
`NoInspectionAvailable`/`Could not locate name 'User | None'`. This is a real
error you hit if you write the natural modern annotation in quotes.

## Rule 3: M2M writes go through link tables

`app/services/tasks.py`:

```python
async def _set_task_labels(db, task_id, label_ids):
    await db.execute(delete(TaskLabelLink).where(TaskLabelLink.task_id == task_id))
    if label_ids:
        await db.execute(
            insert(TaskLabelLink),
            [{"task_id": task_id, "label_id": lid} for lid in label_ids],
        )
```

Why not `task.labels = await _resolve_labels(...)`?

Assigning to an ORM collection triggers a **lazy load of the existing
collection** (to diff it) — in an async session that is an implicit I/O in a
context where SQLAlchemy can't await → `MissingGreenlet`. Even when it doesn't
crash (fresh objects), you're doing the diff in Python with extra queries.

Direct link-table writes are:

- explicit (the DELETE+INSERT is readable),
- one round trip for the delete, one for the insert,
- independent of ORM collection state.

After writing, the service re-fetches the task so the relationship *is* loaded
for the response (`_set_task_labels` docs and `refetch_task`).

## Rule 4 (sequel): identity-map staleness and `populate_existing`

`app/services/tasks.py`:

```python
async def refetch_task(db: AsyncSession, task_id: uuid.UUID) -> Task:
    statement = (
        select(Task)
        .where(Task.id == task_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(statement)).scalar_one()
```

The comment on this function documents a bug it fixes: after
`_set_task_labels`, the `Task` object is already in the session's identity map
with an *empty* `labels` collection (loaded when `TaskAccess` fetched it). A
plain re-`select()` returns the same object and — by default — **does not
refresh already-populated collections**, so the API would return
`labels: []` right after assigning a label. `populate_existing=True` forces
eager loaders to repopulate.

This is exactly the kind of subtlety you will review for in generated code.
Symptom: "the write works, the response is stale".

## The link models

```python
class TaskLabelLink(SQLModel, table=True):
    __tablename__ = "task_labels"
    __table_args__ = (UniqueConstraint("task_id", "label_id", name="uq_task_label"),)
    task_id: uuid.UUID = Field(sa_column=Column(SAUuid(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True))
    label_id: uuid.UUID = Field(sa_column=Column(SAUuid(as_uuid=True),
        ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True))
```

Two details:

- **Defined before `Task`** in the module: SQLModel's `link_model=` takes the
  class object, and the `Relationship` is declared in the class body — so the
  class must already exist. (Forward references don't work for `link_model`.)
- The composite PK `(task_id, label_id)` plus the unique constraint make link
  rows idempotent: inserting the same pair twice fails loudly instead of
  duplicating.

## What TeamFlow deliberately does NOT have

| Missing relationship | Why |
| --- | --- |
| `User.tasks` (reverse) | nothing iterates a user's tasks via ORM; queries go through repositories |
| `Project.tasks` | same; aggregates are SQL |
| `Organization.*` collections | org deletion is a DB cascade, not ORM traversal |
| `Membership.organization` | the org is fetched once per request by the dependency; a relationship would add a join for nothing |

This is "declare only what you read" in practice. Every relationship you add is
an eager-load strategy you must remember on every query that touches the model.

## Django comparison 🔵

| Django | SQLModel |
| --- | --- |
| `task.assignee` lazily queries on access (sync) | async: lazy access raises `MissingGreenlet` — eager strategies are mandatory |
| `select_related("assignee")` per queryset | `lazy="joined"` on the relationship (automatic) |
| `prefetch_related("labels")` | `lazy="selectin"` on the collection |
| `task.labels.set([...])` / `.add()` | link-table `INSERT/DELETE` |
| `related_name` reverse managers | not needed; query explicitly |

Django lets you be lazy and fixes N+1 with `select_related`/`prefetch_related`
per query. Async SQLAlchemy *cannot* be lazy, so TeamFlow moves the eagerness
into the model definition — closer to DRF's `Meta.depth` in spirit, but exact
about the SQL it produces.

## Production perspective

- **`joined` on hot paths** is a real JOIN in the main query; with multiple
  many-to-one relationships the query widens. TeamFlow's `tasks` list joins two
  users (creator/assignee) — acceptable; ten joined relationships would not be.
- **`selectin` collections** add exactly one query per collection per page.
  Three collections → three extra queries regardless of page size (up to the
  IN-clause size). Still O(1) in page size, not O(n).
- **Write paths re-fetch** (`refetch_task`, membership refetch in
  `add_member_direct`) — one extra SELECT buys correct, fully-loaded
  responses. Cheap next to the correctness risk.
- **Never `expire_on_commit=True`** with these relationships (default would
  force refresh-on-access → lazy load → crash).

## Common mistakes

1. `task.labels.append(label)` in an async service — `MissingGreenlet` or an
   implicit load you didn't intend.
2. Using `"User | None"` in the annotation — SQLModel can't resolve it.
   `Optional["User"]` works.
3. Omitting `foreign_keys` when two FKs point at the same table — SQLAlchemy's
   `AmbiguousForeignKeysError` at mapper configuration time.
4. Re-`select()`ing after a write and returning stale collections — missing
   `populate_existing=True` (TeamFlow's `refetch_task` comment is the war story).
5. Adding relationships "for convenience", then discovering every list query
   got heavier because the strategy is eager.

## Cheat sheet

```python
assignee: Optional["User"] = Relationship(
    sa_relationship_kwargs={"lazy": "joined", "foreign_keys": "Task.assignee_id"})
labels: list["Label"] = Relationship(
    link_model=TaskLabelLink, sa_relationship_kwargs={"lazy": "selectin"})

# writes:
await db.execute(delete(TaskLabelLink).where(...))
await db.execute(insert(TaskLabelLink), [{"task_id": ..., "label_id": ...}])
task = await refetch_task(db, task.id)   # populate_existing=True
```

## Review questions

1. Why does `tasks` need `foreign_keys` on both relationships?
2. What SQL does `task.labels` (selectin) produce for a page of 20 tasks?
3. Why is `task.labels = [...]` dangerous in an async session?
4. When exactly does `populate_existing=True` matter, and what is the user-visible
   symptom if you forget it?
