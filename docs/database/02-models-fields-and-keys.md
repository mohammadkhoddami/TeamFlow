# Database 02 — Models, Fields, and Keys

## Concept

A table is: columns (typed, constrained), a primary key, foreign keys with
delete behavior, and indexes. TeamFlow makes each of these explicit in
`app/models/*.py` because they encode security and performance policy, not just
shape.

## The tenant-column rule

Every tenant-owned table carries `organization_id` with an FK cascade:

```python
# app/models/task.py
organization_id: uuid.UUID = Field(
    sa_column=Column(
        SAUuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
)
```

This single column is what makes tenant isolation cheap and reliable:
`WHERE organization_id = :org` is the first condition on every query, and
org deletion is one DB statement (`DELETE FROM organizations WHERE id=...`)
rather than an ORM traversal. See `auth/07-multi-tenancy.md`.

## Primary keys: UUIDv4 everywhere

```python
id: uuid.UUID = Field(default_factory=uuid.uuid4, sa_type=Uuid(as_uuid=True), primary_key=True)
```

Trade-offs, stated honestly:

| Property | UUIDv4 (chosen) | Bigserial |
| --- | --- | --- |
| Enumerable | no | yes (IDOR-adjacent info leak) |
| Generation | client-side, before INSERT | DB round trip |
| Index locality | poor (random inserts) | good |
| Size | 16 bytes | 8 bytes |

At TeamFlow's scale locality is irrelevant; the non-enumerability and
client-side generation win. (For very hot tables, UUIDv7 would be the modern
middle ground — noted in `database/09-database-performance.md`.)

## Foreign key delete behavior — the full table

| FK | On delete | Why |
| --- | --- | --- |
| `*` → `organizations.id` | `CASCADE` | deleting a tenant deletes its world |
| `tasks` → `projects.id` | `CASCADE` | a project's tasks have no meaning without it |
| `comments`/`attachments` → `tasks.id` | `CASCADE` | same |
| `task_labels`/`task_watchers` link rows | `CASCADE` | relationship rows |
| `*.created_by_id`/`owner_id`/`assignee_id`/`uploader_id` | `SET NULL` | keep the row if the user is deleted; attribution is best-effort |
| `notifications` → `users.id` | `CASCADE` | a deleted user's inbox is meaningless |
| `idempotency_keys` → `users.id` | `CASCADE` | ditto |
| `webhook_deliveries` → `webhooks.id` | `CASCADE` | delivery history belongs to the hook |

Why DB-level cascades rather than SQLAlchemy `cascade="all, delete-orphan"`
on relationships? In async sessions, ORM cascades require loading every child
collection before delete — expensive and easy to get wrong. One `DELETE` with
`ON DELETE CASCADE` is atomic, fast, and visible in the migration. The cost:
you must trust the DB (which you should).

## `SET NULL` requires nullable columns

```python
created_by_id: uuid.UUID | None = Field(
    default=None,
    sa_column=Column(SAUuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
)
```

Services treat these as optional in reads: `TaskRead.creator: UserRead | None`.

## Unique constraints and indexes — where policy lives

| Table | Constraint | Purpose |
| --- | --- | --- |
| `users.email` | unique index | login identity |
| `organizations.slug` | unique index | URL identity (tenant isolation entry point) |
| `memberships (user_id, organization_id)` | `uq_membership_user_org` | one role per user per org |
| `labels (organization_id, name)` | `uq_label_org_name` | no duplicate labels per org |
| `task_labels (task_id, label_id)` | `uq_task_label` | idempotent assignment |
| `task_watchers (task_id, user_id)` | `uq_task_watcher` | ditto |
| `attachments.storage_key` | unique | S3 key collision guard |
| `idempotency_keys.key` | unique | **the** race arbiter (`fastapi/08`) |
| `invitations (organization_id, email)` | plain index | service checks pending uniqueness |

⚠️ Note the last row: pending-invitation uniqueness is **not** a DB constraint.
A partial unique index (`WHERE status = 'pending'`) would be the strict answer;
TeamFlow enforces it in `app/services/invitations.py`
(`get_pending_for_email`) and documents the trade-off — a rare race could
create two pending invites. That is a deliberate simplification, not an
oversight; the fix is one Alembic migration if it ever matters.

## Composite and covering indexes on `tasks`

```python
__table_args__ = (
    Index("ix_tasks_org_project_status", "organization_id", "project_id", "status"),
    Index("ix_tasks_org_status", "organization_id", "status"),
    Index("ix_tasks_assignee", "assignee_id"),
    Index("ix_tasks_due_date", "due_date"),
    Index("ix_tasks_created", "created_at"),
)
```

These mirror the real query shapes (`database/07-indexes-and-constraints.md`
shows the EXPLAIN reasoning):

- dashboard status counts → `(organization_id, status)`;
- project board filtered by status → `(organization_id, project_id, status)`;
- "my tasks" and per-member stats → `assignee_id`;
- overdue scan → `due_date`;
- default sort → `created_at`.

Indexes are not free: each one slows writes and costs storage. TeamFlow adds
only indexes that match existing query patterns — five on `tasks`, none
"just in case".

## JSON columns

| Column | Model | Use |
| --- | --- | --- |
| `notifications.data` | `dict \| None` | task/project ids for deep links |
| `webhooks.events` | `list[str]` | subscribed event names |
| `webhook_deliveries.payload` | `dict` | frozen event body |
| `audit_logs.meta` | `dict \| None` | sanitized context |
| `idempotency_keys.response_body` | `Text` | replay payload |

JSON is right for **open-ended payloads that are never filtered by inner
keys**. `webhooks.events` is a borderline case: matching happens in Python
(`active_for_org_and_event` filters in memory) because webhook counts per org
are tiny. If webhooks grew per-org, a `jsonb` containment query (`events @>
'["task.created"]'`) or a join table would be the upgrade — noted in the
repository docstring.

## Django comparison 🔵

| Django | SQLModel/SQLAlchemy |
| --- | --- |
| `on_delete=models.CASCADE` | `ForeignKey(..., ondelete="CASCADE")` |
| `models.UniqueConstraint(fields=[...], name=...)` | `UniqueConstraint("a", "b", name=...)` |
| `db_index=True` | `Column(..., index=True)` |
| `Meta.indexes` | `__table_args__ = (Index(...),)` |
| `related_name` (reverse accessor) | relationships are explicit, no reverse unless declared |

Django relationships are ORM-level objects with cascades enforced in Python;
TeamFlow puts delete behavior in the database and keeps ORM relationships to
*one side* (next lesson).

## Review questions

1. Why is `organization_id` on every table instead of joining to `projects` to
   find the tenant?
2. Which cascades are `SET NULL`, and what user-facing behavior does that
   produce when a user is deleted?
3. Why is `idempotency_keys.key` unique, and what breaks if it isn't?
4. Pick an index on `tasks` and describe the exact query it accelerates.
