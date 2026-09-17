# Mastery 02 — SQLModel Cheat Sheet

## Models

```python
class Thing(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "things"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_thing_org_name"),
        Index("ix_things_org_status", "organization_id", "status"),
    )
    organization_id: uuid.UUID = Field(sa_column=Column(
        SAUuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    ))
    name: str = Field(sa_column=Column(String(64), nullable=False))
    status: str = Field(sa_column=Column(String(16), nullable=False))

    def __init__(self, **kwargs: object) -> None:      # sa_column defaults
        kwargs.setdefault("status", "active")
        super().__init__(**kwargs)
```

Rules that bite:

```
mixin column       → sa_type= / sa_column_kwargs=   (never sa_column)
sa_column          → nullable/default live on the Column; use __init__ defaults
two FKs to 1 table → sa_relationship_kwargs={"foreign_keys": "Task.assignee_id"}
relationship       → Optional["User"] (string union "User | None" fails)
relationship       → lazy="joined" (scalar) / lazy="selectin" (collection)
link model         → define BEFORE the class that references it
```

## Sessions

```python
engine = create_async_engine(url, pool_size=10, max_overflow=10, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession,
                                       expire_on_commit=False, autoflush=False)

async with AsyncSessionLocal() as session:      # implicit transaction
    ...
```

```
add → flush → commit → refresh (if needed)      service owns commit
expire_on_commit=False  → no lazy refresh after commit (async-safe)
```

## Queries

```python
select(M).where(M.col == x, M.col2.in_(...))
(await db.execute(stmt)).scalar_one_or_none()   # 0..1
(await db.execute(stmt)).scalars().all()        # list
select(func.count(M.id)).where(*conds)          # count
select(M.status, func.count(M.id)).group_by(M.status)
func.count(M.id).filter(M.due_date < now, ...)  # FILTER aggregates
or_(M.title.ilike(f"%{term}%"), ...)            # bound param, never f-string SQL
M.id.in_(select(Link.m_id).where(Link.x == y))  # subquery instead of join
update(M).where(...).values(...)                # bulk update
delete(M).where(...)                            # bulk delete
stmt.execution_options(populate_existing=True)  # refresh already-loaded collections
with_for_update()                               # row lock (idempotency only)
```

## Relationship writes (async-safe)

```python
# NOT: task.labels = [...]            (implicit lazy load → MissingGreenlet)
await db.execute(delete(TaskLabelLink).where(TaskLabelLink.task_id == task.id))
await db.execute(insert(TaskLabelLink), [{"task_id": ..., "label_id": ...}])
task = await refetch_task(db, task.id)     # populate_existing=True
```

## Loading / N+1

```
page query (1) + count (1) + collections (K selectin) = O(1) per page
many-to-one → lazy="joined"      collections → lazy="selectin"
fresh object → re-select before serialize
membership with user → refetch after add (fresh instances aren't eager-loaded)
```

## Migrations

```bash
alembic revision --autogenerate -m "message"
alembic upgrade head
alembic downgrade base
# env.py: target_metadata = SQLModel.metadata, url from settings, async engine
```

## Django ORM mapping

| Django | SQLModel |
| --- | --- |
| `User.objects.filter(...)` | `select(User).where(...)` |
| `.get(pk=...)` | `db.get(User, pk)` / `.scalar_one_or_none()` |
| `select_related` / `prefetch_related` | `lazy="joined"` / `lazy="selectin"` |
| `annotate(Count(...))` | `func.count(...)` + `group_by` |
| `Q(...)` | `or_(...)` / `and_(...)` |
| `auto_now_add` / `auto_now` | `default_factory=utcnow` / `onupdate=utcnow` |
| `unique_together` / `Meta.indexes` | `UniqueConstraint` / `Index` in `__table_args__` |
| `on_delete=CASCADE` | `ondelete="CASCADE"` on the FK |
| `.save()` (immediate) | `add` + `flush`; service `commit`s |
