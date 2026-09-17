# Auth 01 — Authentication

## Concept

Authentication answers **"who is this?"** (identity). Authorization answers
**"what may they do?"** (permission). TeamFlow implements authentication with
JWT bearer tokens and authorization with org memberships + role ranks.

This lesson covers identity: register → login → token → dependency.

## The flow

```
POST /api/v1/auth/register   → creates User (bcrypt hash)
POST /api/v1/auth/login      → verifies password → Access JWT + Refresh JWT
                              (refresh JTI whitelisted in Redis)
GET  /api/v1/auth/me         → Authorization: Bearer <access JWT>
                              → CurrentUser dependency → User row
```

## TeamFlow implementation

### Register — `app/services/auth.py`

```python
async def register_user(db: AsyncSession, data: UserCreate, ip: str | None = None) -> User:
    repo = UserRepository(db)
    if await repo.get_by_email(data.email):
        raise ConflictError("A user with this email already exists")
    user = User(
        email=data.email,
        full_name=data.full_name,
        hashed_password=security.hash_password(data.password),
    )
    user = await repo.add(user)
    await audit.log(db, AuditAction.USER_REGISTERED, actor_id=user.id, ip=ip,
                    meta={"email": user.email})
    await db.commit()
    await db.refresh(user)
    return user
```

- The plaintext password exists only in memory for the duration of the hash
  call — never stored, never logged, never in audit meta.
- Registration is rate limited per IP (`app/core/rate_limit.py`), so account
  spam costs the attacker a slow drip.

### Login — response and timing

```python
async def login(db, redis, email, password, ip=None) -> Token:
    await hit_rate_limit(redis, "auth_email", email.lower(),
                         settings.auth_rate_limit_max, settings.auth_rate_limit_window)

    user = await UserRepository(db).get_by_email(email)
    if not user or not security.verify_password(password, user.hashed_password):
        await audit.log(db, AuditAction.USER_LOGIN_FAILED, ip=ip, meta={"email": email})
        await db.commit()
        raise UnauthorizedError("Incorrect email or password")   # deliberately vague
    if not user.is_active:
        raise UnauthorizedError("Account is deactivated")
    ...
```

Three security decisions to internalize:

1. **Identical error for unknown email and wrong password** — no user
   enumeration. (`tests/integration/test_auth_flow.py` asserts both produce the
   same 401 message.)
2. **Per-email rate limit before password verification** — floods burn quota
   before any bcrypt work happens, and a victim's account can't be locked out
   by IP alone (the email key separates identities).
3. **Failed logins are audited** (`USER_LOGIN_FAILED`) — forensics without
   leaking anything (meta holds the email only, not the password).

### The authentication dependency — `app/api/deps.py`

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
Token = Annotated[str, Depends(oauth2_scheme)]

async def get_current_user(token: Token, db: DB) -> User:
    try:
        payload = security.decode_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (PyJWTError, KeyError, ValueError):
        raise UnauthorizedError("Invalid or expired token") from None

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or deactivated")
    user_id_ctx.set(str(user.id))
    return user

CurrentUser = Annotated[User, Depends(get_current_user)]
```

- One JWT decode + one indexed PK lookup per authenticated request. That is the
  entire per-request auth cost (the JWT is stateless — no Redis read; the
  trade-off is discussed in `auth/04-access-and-refresh-tokens.md`).
- `is_active` is checked on **every** request, so deactivating a user takes
  effect within one access-token lifetime (30 min) even though the token is
  still cryptographically valid.
- The contextvar binding means every subsequent log line carries `user_id`.

### Profile

`GET /auth/me` and `PATCH /auth/me` are thin: `CurrentUser` in, `UserRead` out,
`auth.update_user` handles the email-uniqueness check
(`ConflictError` → 409).

## Endpoint inventory (auth)

| Endpoint | Purpose | Auth |
| --- | --- | --- |
| `POST /auth/register` | create account | rate limited |
| `POST /auth/login` | OAuth2 password flow (form-encoded) | rate limited (IP + email) |
| `POST /auth/refresh` | rotate token pair | refresh JWT |
| `POST /auth/logout` | revoke one refresh token | refresh JWT |
| `POST /auth/logout-all` | revoke every session | access JWT |
| `GET /auth/me` | profile | access JWT |
| `PATCH /auth/me` | update profile | access JWT |
| `POST /auth/forgot-password` | email reset link | rate limited, always 202 |
| `POST /auth/reset-password` | redeem single-use token | rate limited |

## Django/DRF comparison 🔵

| DRF | TeamFlow |
| --- | --- |
| `TokenAuthentication` / `JWTAuthentication` class | `oauth2_scheme` + `get_current_user` dependency |
| `DEFAULT_AUTHENTICATION_CLASSES` (global) | `CurrentUser` parameter (per route, explicit) |
| `request.user` | the dependency's return value |
| `LoginView` (session) | `POST /auth/login` issuing JWTs |
| `IsAuthenticated` permission | declaring `CurrentUser` (absence = public) |

DRF configures authentication globally and applies it via permissions. FastAPI
makes it an opt-in parameter — a public route simply doesn't ask for
`CurrentUser`. The review discipline that replaces DRF's global default: **every
route must either declare `CurrentUser` or be intentionally public** (health,
register, login, refresh, forgot/reset).

## Production perspective

- **Access tokens are short-lived and stateless** — revocation is bounded by
  TTL, not instant. Deactivation is enforced per request via `is_active`.
- **Clock skew**: JWT `exp` is checked by PyJWT with zero leeway; in fleet
  deployments with skewed clocks, allow small leeway
  (`jwt.decode(..., leeway=...)`). Noted as a deployment hardening.
- **HTTPS is mandatory** — bearer tokens in `Authorization` headers; TLS
  termination lives at nginx (`production/03-nginx.md`).
- **Logging**: tokens are never logged; the access-log middleware logs
  method/path/status only, and the `Authorization` header is never captured.

## Common mistakes

1. **Different error messages for unknown user vs bad password** — enumeration.
2. **Checking `is_active` only at login** — deactivated users keep working until
   token expiry. TeamFlow checks per request.
3. **Putting the password hash in a response schema** — impossible here because
   `UserRead` doesn't have the field.
4. **Trusting `payload["sub"]` as an int/str inconsistently** — TeamFlow stores
   the UUID string and parses defensively (`ValueError` → 401).
5. **Using the refresh token as an access token** — rejected because
   `get_current_user` never checks `type`... it *accepts* any valid signature!
   Wait: check this. `get_current_user` decodes and takes `sub` without
   verifying `payload["type"] == "access"`.

⚠️ **Honest security note**: TeamFlow's `get_current_user` does **not** verify
the token type, while `authenticate_socket` (WS) and `refresh_tokens` **do**.
A stolen refresh token could therefore be used as an access token on HTTP
routes (it has the same signing key and a longer TTL). The fix is one line
(`if payload.get("type") != security.TOKEN_TYPE_ACCESS: raise UnauthorizedError`).
This is exactly the kind of issue a review must catch — it is documented here
rather than silently patched per the course rules. See
`production/07-security.md`.

## Cheat sheet

```python
# create
user = User(email=..., hashed_password=security.hash_password(pw))
# verify
ok = security.verify_password(pw, user.hashed_password)
# authenticate a request
async def get_current_user(token: Token, db: DB) -> User: ...
CurrentUser = Annotated[User, Depends(get_current_user)]
```

## Review questions

1. Why is the per-email rate limit checked before password verification?
2. What is the per-request cost of `CurrentUser` (queries, Redis calls)?
3. Why does `is_active` get checked on every request instead of at login only?
4. Find the token-type gap in `get_current_user` and describe the exact attack
   it enables.
