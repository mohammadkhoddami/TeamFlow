# FastAPI 05 — Pydantic Validation

## Concept

Pydantic v2 is FastAPI's validation/serialization engine. Every request body,
every response model, and every settings object is a Pydantic model. SQLModel
schemas in TeamFlow *are* Pydantic models (`SQLModel` subclasses `BaseModel`).

## Why it exists

Django/DRF devs know this as "serializer validation with `validate_*` methods and
`required=False`". Pydantic makes it declarative: types + constraints on the
field line, custom logic in validators, and the same model works for requests,
responses, and OpenAPI.

## Mental model

```
HTTP JSON ──► Pydantic model (validation) ──► your function (valid data)
ORM object ──► Pydantic model (from_attributes) ──► JSON response
env vars  ──► Settings model ──► typed config object
```

Validation happens **before** your code runs. If a handler executes, its inputs
already satisfy the declared types and constraints.

## TeamFlow implementation

### Field constraints

`app/schemas/auth.py`:

```python
class UserCreate(SQLModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(default="", max_length=255)
```

- `EmailStr` uses `email-validator` (installed in `pyproject.toml`); invalid
  emails are 422s before bcrypt ever runs.
- `min_length=10` is a policy decision enforced at the edge — the same rule
  should exist in one place only, here.

### Literal enums for closed sets

`app/schemas/task.py`:

```python
StatusLiteral = Literal["todo", "in_progress", "in_review", "done"]
PriorityLiteral = Literal["low", "medium", "high", "urgent"]
```

This is the Pydantic-idiomatic replacement for DRF `ChoiceField`. Benefits:
OpenAPI gets enum values, typos are 422s, and the *source of truth* is shared
with the model constants in `app/models/task.py` via review convention (change
one, change the other — they are intentionally not imported to keep schemas
independent of DB internals).

### Custom validators

`app/schemas/label.py`:

```python
class LabelCreate(SQLModel):
    name: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=9)

    @field_validator("color")
    @classmethod
    def color_hex(cls, v: str | None) -> str | None:
        if v is not None and not (v.startswith("#") and len(v) == 7):
            raise ValueError("color must be #RRGGBB")
        return v
```

`field_validator` is the Pydantic v2 replacement for DRF's
`validate_color`. It runs only when the field is present.

### Regex-constrained strings

```python
# app/schemas/organization.py
slug: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
                  min_length=2, max_length=63)
```

Slugs are used in URLs (`/organizations/{slug}/...`) so the pattern is a
URL-safety measure, not cosmetics.

### URL validation for webhooks

```python
# app/schemas/webhook.py
from pydantic import AnyHttpUrl

class WebhookCreate(SQLModel):
    url: AnyHttpUrl
    events: list[WebhookEventLiteral] = Field(min_length=1, max_length=10)
```

`AnyHttpUrl` rejects `ftp://`, `file://`, and relative URLs — a real
SSRF-adjacent control (fully blocking internal addresses would need a custom
validator; see `production/07-security.md` for the gap and how to close it).

### Model configuration and from-attributes

TeamFlow's read schemas validate from ORM objects:

```python
return UserRead.model_validate(current_user)     # current_user is a table model
```

SQLModel enables `from_attributes` behavior for these conversions. For nested
lists (`labels: list[LabelRead]`) Pydantic walks the ORM attributes recursively.

### Generics

`Page[T]` (`app/schemas/common.py`) is a Pydantic v2 generic — see
`04-response-models.md`.

## Validation errors: the shape

FastAPI's default 422 body is verbose and includes Python internals in `ctx`.
TeamFlow normalizes it in `app/core/exceptions.py`:

```python
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc):
    errors = [
        {"loc": ".".join(str(p) for p in err.get("loc", [])),
         "msg": err.get("msg", "invalid"),
         "type": err.get("type", "value_error")}
        for err in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})
```

Stable error shape = easier client code + no leaked `PydanticCustomError`
contexts.

## Django/DRF comparison 🔵

| DRF | Pydantic v2 |
| --- | --- |
| `serializers.CharField(max_length=255)` | `str = Field(max_length=255)` |
| `EmailField()` | `EmailStr` |
| `ChoiceField(choices=[...])` | `Literal[...]` |
| `validate_<field>()` | `@field_validator("<field>")` |
| `validate()` (cross-field) | `@model_validator(mode="after")` |
| `required=False` | `X \| None = None` |
| `serializer.errors` → 400 (DRF) | auto-422 (FastAPI) |

**Status code difference to internalize:** DRF returns 400 for validation
errors; FastAPI returns **422**. TeamFlow keeps 422 (it is the FastAPI
convention) and documents it in OpenAPI.

## Production perspective

- Validation cost is CPU-bound and small; it happens in the event loop before
  any I/O. Keep validators pure (no DB calls) — a validator that queries the DB
  blocks the event loop and couples schema to infrastructure. That check belongs
  in the service (e.g., "assignee must be an org member" is in
  `app/services/tasks.py`, *not* in `TaskCreate`).
- Schemas are the contract; changing one is an API change.
- `Field(max_length=...)` on text that goes into the DB also caps payload sizes
  — cheap DoS protection.

## Common mistakes

1. **DB access in validators.** Looks convenient, blocks the loop, breaks
   layering, and can't use the request's transaction.
2. **One schema for create/update/read.** You end up with `extra="ignore"`-style
   loopholes. TeamFlow keeps separate `*Create`, `*Update`, `*Read`.
3. **Expecting 400.** Client code written for DRF will mishandle 422 — document
   it.
4. **Mutable defaults without `default_factory`.** `label_ids: list = []` is a
   shared-list bug; TeamFlow uses `Field(default_factory=list)`.
5. **Trusting client-provided tenant/role fields.** No TeamFlow request schema
   contains `organization_id` or `role`-of-actor; those are resolved server-side
   (`auth/07-multi-tenancy.md`).

## Cheat sheet

```python
class ThingCreate(SQLModel):
    name: str = Field(min_length=1, max_length=64)
    kind: Literal["a", "b"]
    tags: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    url: AnyHttpUrl | None = None

    @field_validator("name")
    @classmethod
    def no_pipes(cls, v: str) -> str: ...
```

## Review questions

1. Why does "assignee must be a member" live in the service and not in a
   `field_validator`?
2. What HTTP status does an unknown `priority="critical"` produce, and why?
3. Where would you add validation for "due_date cannot be in the past" and
   why? (Hint: is it a property of the value, or of the business state?)
4. Why does TeamFlow normalize the 422 body shape?
