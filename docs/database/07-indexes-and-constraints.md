# Database 07 — Indexes and Constraints

## Concept

An index is a sorted structure the database maintains to answer certain
`WHERE`/`ORDER BY` patterns without scanning the table. A constraint is a rule
the database enforces (unique, not-null, foreign key) — constraints are
correctness, indexes are performance.

## Why they exist in TeamFlow

Every query in this system starts with `organization_id = :org`. Without an
index, each tenant's queries scan other tenants' rows — the classic multi-tenant
performance cliff. Constraints prevent states the application assumes can't
exist (duplicate memberships, duplicate labels), which in turn lets services
skip defensive re-checks.

## The index inventory (with the query each one serves)

### `tasks`

```python
__table_args__ = (
    Index("ix_tasks_org_project_status", "organization_id", "project_id", "status"),
    Index("ix_tasks_org_status", "organization_id", "status"),
    Index("ix_tasks_assignee", "assignee_id"),
    Index("ix_tasks_due_date", "due_date"),
    Index("ix_tasks_created", "created_at"),
)
```

| Index | Query it serves |
| --- | --- |
| `(organization_id, project_id, status)` | project board: `WHERE org=? AND project=?` [+ status filter] |
| `(organization_id, status)` | dashboard status counts `GROUP BY status WHERE org=?`; filtered lists |
| `(assignee_id)` | "my tasks", per-member aggregates |
| `(due_date)` | `?overdue=true`, `?due_before=`, due-soon reminders |
| `(created_at)` | default `ORDER BY created_at DESC` page |

Plus the implicit `project_id` index from `index=True` on the FK column —
adding an explicit composite that already leads with `organization_id, project_id`
makes the standalone FK index partly redundant; at this scale it's harmless
(writes are not index-bound yet).

### Other tables

| Index/constraint | Table | Serving |
| --- | --- | --- |
| unique `email` | users | login lookup + duplicate prevention |
| unique `slug` | organizations | URL resolution + uniqueness |
| unique `(user_id, organization_id)` | memberships | the core auth check; prevents double membership |
| unique `(organization_id, name)` | labels | label uniqueness per org |
| unique `(task_id, label_id)` / `(task_id, user_id)` | link tables | idempotent assignment |
| `(task_id, created_at)` | comments, attachments | chronological listing per task |
| `(user_id, read_at)` | notifications | unread count / inbox listing |
| `(organization_id, created_at)` | audit_logs | admin trail pagination |
| `(webhook_id, created_at)` | webhook_deliveries | delivery history |
| `(organization_id, email)` | invitations | pending-invite lookup |
| unique `key` | idempotency_keys | the race arbiter |
| `(created_at)` | idempotency_keys | cleanup purge |

`(user_id, read_at)` deserves a note: the unread count is
`WHERE user_id=? AND read_at IS NULL` — PostgreSQL can use the composite index
for the user prefix and filter nulls cheaply. A partial index
(`WHERE read_at IS NULL`) would be even tighter; the composite is simpler and
fine at this scale.

## Constraints as application assumptions

Examples where a constraint *replaces* service code:

```python
# memberships — the unique constraint makes this race-free
UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org")
```

The service still checks first (`get_for_user`) for a friendly 409, but the
constraint is the real guarantee: two concurrent "add member" requests cannot
both succeed, regardless of the check-then-insert gap.

```python
# idempotency_keys
key: str = Field(sa_column=Column(String(128), unique=True, nullable=False))
```

This unique index *is* the idempotency algorithm (`database/06-transactions.md`).

## Reading a query plan (how to verify an index matters)

```sql
EXPLAIN ANALYZE
SELECT * FROM tasks
WHERE organization_id = '...' AND status = 'todo'
ORDER BY created_at DESC
LIMIT 20;
```

What you want to see: `Index Scan using ix_tasks_org_status` (or an index scan
on the composite), not `Seq Scan on tasks`. TeamFlow's indexes exist precisely
so the four hottest patterns (board, dashboard, my-tasks, overdue) are index
scans.

Two patterns here intentionally do **not** use indexes:

- `search ILIKE '%term%'` — leading wildcard defeats B-tree; needs `pg_trgm`
  GIN at scale.
- `ORDER BY priority` — low-cardinality column; Postgres will often sort in
  memory rather than walk an index. Fine for bounded pages.

## Django comparison 🔵

| Django | SQLModel/SQLAlchemy |
| --- | --- |
| `db_index=True` | `Column(..., index=True)` |
| `unique_together` | `UniqueConstraint("a","b")` |
| `Meta.indexes = [models.Index(fields=[...])]` | `__table_args__ = (Index(...),)` |
| `constraints = [CheckConstraint(...)]` | `CheckConstraint` in `__table_args__` |

One Django habit to drop: `constraints` in `Meta` vs `__table_args__` — in
SQLAlchemy everything table-level goes through `__table_args__`.

## Production perspective

- **Indexes slow writes.** Each INSERT maintains every index. TeamFlow's hot
  write path (`tasks`) carries five indexes plus FKs — acceptable now; the
  first thing to review if write latency grows.
- **Migrations create indexes non-concurrently by default** — on large tables
  use `CREATE INDEX CONCURRENTLY` (Alembic:
  `op.create_index(..., postgresql_concurrently=True)` plus `autocommit_block`).
  Not needed for the initial migration; relevant for live systems.
- **Partial indexes are the lever for sparse conditions** (e.g. `status != 'done'`
  overdue queries on huge tables).
- **The initial migration is the schema's source of truth** — index names in
  `migrations/versions/f699cd23df0b_initial_schema.py` match the models, so
  `alembic upgrade head` on an empty DB reproduces exactly what
  `SQLModel.metadata.create_all` would (tests use the latter).

## Common mistakes

1. **Indexing everything** "for safety" — write amplification for no read gain.
2. **Forgetting the tenant column in composite indexes** — an index on
   `(status)` alone is nearly useless when every query filters by org.
3. **`LIKE '%x%'` with a B-tree index expectation** — it won't be used.
4. **Relying on check-then-insert without a constraint** — race conditions.
5. **Adding an index in the model but not in a migration** — production and
   tests diverge (`alembic check`-style review catches this).

## Cheat sheet

```python
__table_args__ = (
    UniqueConstraint("a", "b", name="uq_a_b"),
    Index("ix_table_org_status", "organization_id", "status"),
)
# verify:
# EXPLAIN ANALYZE SELECT ... ; look for Index Scan, not Seq Scan
```

## Review questions

1. Which index serves the dashboard's status counts, and why that column order?
2. Why is `(assignee_id)` indexed without `organization_id`? Is that a problem?
3. How does `uq_membership_user_org` change the concurrency reasoning for
   "add member"?
4. Why will `?search=payment` never use a B-tree index, and what is the fix?
