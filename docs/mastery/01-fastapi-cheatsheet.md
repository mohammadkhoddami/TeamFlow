# Mastery 01 — FastAPI Cheat Sheet

## The app

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    resource = await create()
    yield
    await resource.close()

app = FastAPI(title=..., version=..., lifespan=lifespan, debug=...)
app.exception_handler(AppError)
app.add_middleware(Mw)                 # last added = outermost
app.include_router(router, prefix="/api/v1", tags=["x"])
```

## Routes

```python
router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.get("/{task_id}", response_model=TaskRead)          # path param typed
@router.post("", status_code=201, response_model=TaskRead)  # default success code
@router.delete("/{task_id}", status_code=204)
async def handler(
    data: TaskCreate,                       # JSON body (Pydantic/SQLModel)
    q: str | None = None,                   # query param
    status: list[Literal["todo","done"]] | None = Query(None),
    limit: int = Query(20, ge=1, le=100),   # validated query param
    offset: int = Query(0, ge=0),
    sort: str | None = Query(None, description="'-field' for desc"),
    current_user: CurrentUser,              # dependency (annotated alias)
    access: TaskAccess,
    request: Request,                       # raw request (ip, headers)
    db: DB,
) -> TaskRead: ...
```

## Dependencies

```python
DB = Annotated[AsyncSession, Depends(get_db)]

async def get_current_user(token: Token, db: DB) -> User: ...
CurrentUser = Annotated[User, Depends(get_current_user)]

async def get_task_access(task_id: uuid.UUID, current_user: CurrentUser, db: DB):
    ...  # load + tenant check
TaskAccess = Annotated[tuple[Task, Organization, Membership], Depends(get_task_access)]

def factory(scope, max_hits):
    async def dep(request: Request, redis_client: RedisDep): ...
    return dep
# usage: _rl: None = Depends(factory("login", 5))

# test seam:
app.dependency_overrides[get_storage] = lambda: FakeStorage()
```

## Errors and responses

```python
class NotFoundError(AppError): status_code = 404
raise NotFoundError("Task not found")          # services raise domain errors

@app.exception_handler(AppError)
async def h(request, exc): return JSONResponse(exc.status_code, {"detail": exc.detail}, headers=exc.headers)

@router.post("/x", status_code=202)            # 201 created, 204 no content, 422 validation (FastAPI)
```

## Middleware (pure ASGI)

```python
class Mw:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # wrap send/receive as needed
        await self.app(scope, receive, send)
```

## WebSockets

```python
@router.websocket("/ws/projects/{project_id}")
async def ws(websocket: WebSocket, project_id: uuid.UUID, token: str = Query("")):
    await websocket.accept()
    # auth + authorize BEFORE joining rooms
    try:
        while True:
            msg = await websocket.receive_text()   # validate; never crash
    except WebSocketDisconnect:
        pass
    finally:
        ...  # unregister
```

## OpenAPI

```python
FastAPI(title=..., description=...)
APIRouter(tags=[...])
@router.post(..., summary="...", response_model=..., status_code=...)
OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")   # Swagger Authorize
# /docs /redoc /openapi.json
```

## Traps to remember

| Trap | Rule |
| --- | --- |
| Middleware order | last added runs first |
| Validation status | 422, not 400 |
| V2 annotations in relationships | `Optional["User"]`, not `"User \| None"` |
| `Depends` factory | return the function; wrap at the route |
| Lifespan in tests | ASGITransport skips it; TestClient runs it |
| PATCH null semantics | `data.model_fields_set` |
| Sync work in async | offload with `run_in_threadpool` |
