# FastAPI 13 — OpenAPI & Automatic Documentation

## Concept

FastAPI generates an OpenAPI 3 schema from your routes, schemas, and
dependencies. It serves interactive docs at `/docs` (Swagger UI) and `/redoc`
(ReDoc), plus the raw schema at `/openapi.json`.

## Why it exists

A schema that cannot drift from the code is documentation that stays true.
Every TeamFlow route declaration (types, `response_model`, `status_code`,
`summary`) is also documentation. DRF requires drf-spectacular (or similar);
FastAPI does it from the same declarations that do the work.

## TeamFlow implementation

### App-level metadata — `app/main.py`

```python
app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "TeamFlow API - multi-tenant project management and collaboration.\n\n"
        "**Auth:** OAuth2 password flow via `/api/v1/auth/login` (form-encoded). "
        "Use the access token in `Authorization: Bearer <token>`."
    ),
    debug=settings.debug,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)
```

### Tags group endpoints

```python
router = APIRouter(prefix="/auth", tags=["auth"])
members_router = APIRouter(prefix="/organizations/{slug}/members", tags=["members"])
```

Swagger sections TeamFlow exposes: `health`, `auth`, `organizations`, `members`,
`invitations`, `projects`, `tasks`, `labels`, `comments`, `attachments`,
`notifications`, `webhooks`, `audit`, `dashboard`, `realtime` (WS routes don't
appear in OpenAPI — see limitations below).

### `summary` and `description`

```python
@router.post("/refresh", response_model=RefreshedToken, summary="Rotate tokens")
async def refresh(...): ...

@task_router.post("/{task_id}/move", response_model=TaskRead,
                  summary="Explicit status transition")
async def move_task(...): ...

@dashboard_router.get("", response_model=DashboardStats,
                      summary="Organization statistics")
async def dashboard(...): ...
```

Query params get descriptions too:

```python
sort: str | None = Query(default=None, description="Sortable field, prefix '-' for desc")
```

### Authentication in Swagger

`OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")` in `app/api/deps.py` is
what wires the **Authorize** button: Swagger calls the login form, keeps the
token, and attaches `Authorization: Bearer ...` to "Try it out" requests. The
`tokenUrl` must match the real form-encoded login route:

```python
@router.post("/login", response_model=Token, summary="Login (OAuth2 password flow)")
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], ...):
```

`OAuth2PasswordRequestForm` is exactly the `username`/`password`
`application/x-www-form-urlencoded` contract OAuth2 expects — which is why
login is form-encoded while everything else is JSON. A deliberate protocol
compromise, documented here so reviewers don't "fix" it.

### Response schemas are the contract

Because every route declares `response_model` (or returns 204), the generated
schema includes `UserRead`, `TaskRead`, `Page[TaskRead]`, `DashboardStats`, etc.
`Page[TaskRead]` gets its own generated component — Pydantic v2 generics are
expanded per instantiation.

### Error shapes in docs

TeamFlow's handlers return `{"detail": ...}` consistently, but the OpenAPI
schema only documents the *success* response by default. A production hardening
step (see `production/07-security.md`) is declaring `responses={401: {...},
403: {...}}` per route — TeamFlow keeps routes lean and documents the taxonomy
centrally in `fastapi/09-exception-handling.md`.

## What OpenAPI cannot see

- **WebSocket endpoints** — not part of OpenAPI; TeamFlow documents the message
  protocol in `fastapi/12-websockets.md` and the endpoint docstring.
- **Custom headers like `Idempotency-Key`** — the middleware consumes it before
  routing, so it is not a declared parameter. It *is* advertised in
  `app/main.py`'s description indirectly via CORS `allow_headers`; a doc
  improvement would be an explicit note in the app description.
- **Anything middleware does** (rate limits, request ids).

## Django/DRF comparison 🔵

| DRF | FastAPI |
| --- | --- |
| drf-spectacular + `@extend_schema` | built in, no annotations needed |
| Serializer → schema component | Pydantic/SQLModel schema → component |
| `permission_classes` shown as text | OAuth2 security scheme wired automatically |
| Swagger at `/swagger/` via urls | `/docs`, `/redoc`, `/openapi.json` |

## Production perspective

- **Disable or protect docs in production** if the API is not public
  (`docs_url=None, redoc_url=None` per environment, or an auth dependency on
  the docs routes). TeamFlow leaves them on — a teaching-project choice; the
  hardening path is in `production/07-security.md`.
- **The schema is a build artifact**: clients can generate SDKs from
  `/openapi.json`. Treat schema changes (renames, removed fields) as breaking
  changes.
- Freshness is automatic — a route you forgot to document doesn't exist to
  OpenAPI, so review "does the new endpoint appear in `/docs`?" catches
  registration mistakes.

## Common mistakes

1. **Wrong `tokenUrl`** → Swagger's Authorize button calls a 404 and nobody can
   test authenticated endpoints.
2. **Duplicate handler names** across files → duplicate `operationId`s; Swagger
   UI silently merges/mangles operations.
3. **Missing `response_model`** → the schema shows `{}` and clients can't code
   against it.
4. **Expecting WS routes in `/docs`** — they will never appear.
5. **Leaking internal schemas**: adding `hashed_password` to a `Read` model for
   "convenience" both leaks data *and* documents the leak.

## Cheat sheet

```bash
curl -s http://localhost:8000/openapi.json | python -m json.tool | head
# count paths
curl -s http://localhost:8000/openapi.json | python -c "import json,sys; print(len(json.load(sys.stdin)['paths']))"
```

## Review questions

1. Where exactly is the "Authorize" button's behavior configured, and which
   route must exist for it to work?
2. Why is login form-encoded when every other POST is JSON?
3. Why doesn't `/ws/projects/{id}` show up in `/docs`?
4. What breaks for API clients if a route loses its `response_model`?
