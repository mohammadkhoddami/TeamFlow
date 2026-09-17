# Database 01 — SQLModel

## Concept

SQLModel is a thin layer over Pydantic v2 + SQLAlchemy 2.0. A class that
subclasses `SQLModel` with `table=True` becomes a database table *and* a
Pydantic model. Classes without `table=True` are plain schemas.

```python
class User(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "users"
    email: str = Field(sa_column=Column(String(255), unique=True, index=True, nullable=False))
```

## Why it exists

SQLAlchemy's model layer is powerful but verbose and typed loosely; Pydantic is
excellent for API shapes but has no persistence story. SQLModel unifies the two
so a single mental model covers "what's in the database" and "what's valid
input".

## Mental model

```
SQLModel class
├── table=True   → SQLAlchemy table + Pydantic model (persistence)
└── table=False  → Pydantic model only (API schemas)
```

Both live in the same class family, but **TeamFlow keeps them in separate
packages**:

```
app/models/    table=True   (persistence)
app/schemas/   table=False  (API contract)
```

Why separate even though SQLModel *allows* one class for both? Because a
`TaskRead` needs computed/nested fields the table shouldn't know about
(`watcher_ids`, `assignee: UserRead`), and a `TaskCreate` must never accept
`id`/`created_at`. Separation keeps "what the DB stores" and "what the API
speaks" independently evolvable — the same reason DRF separates models from
serializers, except here both are still one library.

## TeamFlow's model conventions — `app/models/base.py`

```python
def utcnow() -> datetime:
    return datetime.now(UTC)

class UUIDMixin(SQLModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, sa_type=Uuid(as_uuid=True),
                          primary_key=True)

class TimeStampedMixin(SQLModel):
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True),
                                 nullable=False)
    updated_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True),
                                        sa_column_kwargs={"onupdate": utcnow})
```

Three decisions worth internalizing:

1. **UUID primary keys, generated client-side** (`default_factory=uuid.uuid4`).
   No DB sequence, ids are known before INSERT (useful for building payloads),
   and they don't leak row counts. The trade-off: random UUIDs hurt index
   locality at very large scale (see `database/09-database-performance.md`).
2. **`sa_type=Uuid(as_uuid=True)`** — SQLAlchemy's cross-dialect `Uuid`, stored
   as native `UUID` on PostgreSQL. The comment in the file explains why mixins
   must use `sa_type`/`sa_column_kwargs` instead of `sa_column`: a `Column`
   object can only belong to one table, so shared mixins with `sa_column`
   explode on the second model that inherits them.
3. **Timezone-aware timestamps** (`DateTime(timezone=True)`, `datetime.now(UTC)`)
   — never naive datetimes.

⚠️ The mixins accept defaults in `Field(default_factory=...)` but for
`sa_column` fields (see `app/models/user.py`) you must pass `nullable` on the
**Column**, and defaults that matter for INSERT behavior are set in the model's
`__init__`:

```python
class User(...):
    is_active: bool = Field(sa_column=Column(Boolean, nullable=False))

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("is_active", True)
        kwargs.setdefault("is_superuser", False)
        super().__init__(**kwargs)
```

That pattern repeats where a NOT NULL column needs an application default
(`Organization.is_active`, `Task.status/priority`, `Attachment.status`,
`Webhook.is_active`, `Invitation.status`). It's the price of `sa_column`
control; SQLModel does not merge `default=` into the column.

## The add/commit/refresh mental model

```python
# 1. build the object (no DB interaction)
user = User(email=..., hashed_password=...)

# 2. add + flush (INSERT happens, id populated) — inside a repository
repo.add(user)            # self.db.add(user); await self.db.flush()

# 3. the service owns the transaction
await db.commit()         # durable

# 4. refresh if you need DB-generated values/relationships
await db.refresh(user)
```

Why TeamFlow splits it this way:

- **`flush` in repositories, `commit` in services.** A service that creates an
  org *and* its owner membership can't work if the repository commits after the
  org insert — it needs one boundary for both.
- **`expire_on_commit=False`** is configured in `app/core/db.py`:
  ```python
  AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession,
                                         expire_on_commit=False, autoflush=False)
  ```
  With the default (`True`), accessing any attribute after commit triggers a
  refresh — in async that's an implicit lazy load and a `MissingGreenlet`
  crash. `expire_on_commit=False` keeps loaded data usable post-commit.
- **`autoflush=False`** prevents surprise flushes mid-composition; repositories
  call `flush` explicitly.

## Python-side defaults vs server-side defaults

| Default style | Where set | When it fires |
| --- | --- | --- |
| `default_factory=utcnow` | Pydantic/SQLModel | at object construction |
| `Column(..., server_default=...)` | PostgreSQL DDL | at INSERT, if column omitted |
| `__init__` + `setdefault` | Python | at construction (for NOT NULL sa_columns) |

TeamFlow uses Python-side defaults almost everywhere; that keeps the model
authoritative and the DDL simple. The trade-off: raw SQL inserts must supply
values (fine — nothing else writes to these tables).

## Django ORM comparison 🔵

| Django | SQLModel |
| --- | --- |
| `class User(models.Model)` | `class User(SQLModel, table=True)` |
| `models.UUIDField(primary_key=True, default=uuid.uuid4)` | `Field(default_factory=uuid.uuid4, sa_type=Uuid(...), primary_key=True)` |
| `auto_now_add=True` | `default_factory=utcnow` |
| `auto_now=True` | `sa_column_kwargs={"onupdate": utcnow}` |
| `User.objects.create(...)` (saves immediately) | `User(...)` + `session.add()` + `commit()` |
| `select_related`/`prefetch_related` per query | loader strategies on the relationship (`database/08`) |
| `Meta.indexes`, `unique_together` | `__table_args__` (SQLAlchemy `Index`, `UniqueConstraint`) |

The biggest mental shift: **Django's manager methods (`objects.filter`) are
implicit sessions; SQLModel has no manager.** You hold a session and execute
`select()` statements. That explicitness is what makes async possible and what
makes TeamFlow's repository layer meaningful.

## Production perspective

- Models are imported once (via `app/models/__init__.py`) to register all tables
  with the metadata — Alembic autogenerate and `init_db` depend on it.
- Table shape changes are **Alembic migrations**, never `create_all`
  (`production/08-deployment.md` explains why `create_all` exists only for
  tests).
- `sa_column` gives you full SQLAlchemy control when you need it (cascade,
  partial indexes, dialect types) — SQLModel does not fight you.

## Common mistakes

1. **Expecting `default=True` to work with `sa_column`.** It doesn't reach the
   DDL; use `__init__` defaults (TeamFlow's pattern) or `server_default`.
2. **Sharing a `sa_column` through a mixin.** Runtime failure on the second
   model. Use `sa_type`/`sa_column_kwargs` in mixins.
3. **Committing in the model or repository.** Breaks composition; TeamFlow's
   rule is "services commit".
4. **Naive datetimes.** `datetime.utcnow()` (deprecated) produces naive values;
   use `datetime.now(UTC)` like `utcnow()`.
5. **Using table models as API schemas "because SQLModel allows it."** You leak
   columns and couple the wire format to the schema.

## Cheat sheet

```python
class Thing(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "things"
    __table_args__ = (Index("ix_things_org", "organization_id"),)
    organization_id: uuid.UUID = Field(sa_column=Column(
        SAUuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True))
```

## Review questions

1. Why does TeamFlow keep `app/models/` and `app/schemas/` separate when SQLModel
   could serve both?
2. What breaks with `expire_on_commit=True` in an async session?
3. Why do mixins use `sa_type` instead of `sa_column`?
4. Where exactly does the INSERT happen when a service calls
   `repo.add(x)` — and where does durability happen?
