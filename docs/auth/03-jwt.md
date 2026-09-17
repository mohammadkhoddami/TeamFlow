# Auth 03 — JWT

## Concept

A JSON Web Token is a signed, self-contained credential: `header.payload.signature`.
The server verifies the signature and trusts the claims (`sub`, `exp`, `type`,
`jti`) without a database lookup.

## Why it exists

Stateless auth: any API worker can verify a token with the shared secret — no
session store read on every request. The price is that revocation requires
either short TTLs or an auxiliary store (which TeamFlow uses for refresh
tokens only — `auth/04`).

## TeamFlow implementation — `app/core/security.py`

```python
def create_token(subject: str, token_type: str, expires_delta: timedelta,
                 extra_claims: dict[str, Any] | None = None) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)

def decode_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError on invalid/expired tokens; caller handles it."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
```

### Claim by claim

| Claim | Value | Why |
| --- | --- | --- |
| `sub` | user UUID string | identifies the subject |
| `type` | `"access"` / `"refresh"` | prevents cross-use of token classes *if verified* |
| `iat` | issued-at, unix seconds | standard; used by nothing yet (candidate for future max-age checks) |
| `exp` | expiry, unix seconds | PyJWT enforces it; expired tokens raise `ExpiredSignatureError` |
| `jti` | UUID, refresh only | the key under which the refresh token is whitelisted in Redis |

### Algorithm pinning — the classic JWT attack

```python
jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
```

`algorithms=[...]` is **mandatory**. Without it, a library might accept
`alg: none` or confuse HMAC/RSA keys (the historical `alg` confusion attacks).
PyJWT requires the argument for decode — the explicit list here is both a
compile-time habit and a review checkpoint. `settings.jwt_algorithm` defaults to
`HS256`.

### Secret management

```python
# app/core/config.py
secret_key: str = "dev-secret-change-me-in-production"
```

A default exists so `uvicorn` boots without configuration; the `.env.example`
carries generation instructions
(`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Production
hardening — forcing a non-default secret when `ENVIRONMENT=production` — is
noted in `production/07-security.md`.

## Token lifetimes

```python
# app/services/auth.py
ACCESS_TOKEN_EXPIRE_SECONDS = settings.access_token_expire_minutes * 60   # 30 min
REFRESH_TOKEN_EXPIRE_SECONDS = settings.refresh_token_expire_days * 24 * 3600  # 14 days
```

| Token | TTL | Reasoning |
| --- | --- | --- |
| access | 30 min | short enough that revocation lag is tolerable |
| refresh | 14 days | session lifetime; rotated on every use |

## Where JWTs are created and consumed

| Context | File | Notes |
| --- | --- | --- |
| Issued (login/refresh) | `app/services/auth.py` | refresh gets `jti` |
| Verified (HTTP) | `app/api/deps.py` `get_current_user` | **does not check `type`** — see warning |
| Verified (refresh) | `app/services/auth.py` `refresh_tokens` | checks `type == "refresh"` |
| Verified (WebSocket) | `app/websocket/router.py` `authenticate_socket` | checks `type == "access"` |
| Identity for idempotency scoping | `app/core/idempotency.py` `_identity` | best-effort decode, falls back to IP |

⚠️ **Known inconsistency** (documented, not silently fixed): HTTP accepts any
validly-signed token regardless of `type`, while refresh and WS check it. A
refresh token used as an access token therefore works on HTTP routes. One-line
fix: `if payload.get("type") != security.TOKEN_TYPE_ACCESS: raise UnauthorizedError`
in `get_current_user`. This lesson uses it as a review exercise: *consistency of
token-type checks across every verification site*.

## Clock and timezone handling

All timestamps are timezone-aware UTC (`datetime.now(UTC)`); claims are unix
seconds (timezone-free by definition). There is no `nbf` (not-before) claim and
no leeway configured — fine for a single-Region deployment, flagged for
multi-Region (`auth/01` production notes).

## Django/DRF comparison 🔵

| DRF/django | TeamFlow |
| --- | --- |
| `djangorestframework-simplejwt` | hand-rolled `security.py` (~40 lines) |
| `SIMPLE_JWT` settings dict | `settings.*` + service constants |
| `RefreshToken.for_user(user)` | `create_token(str(user.id), "refresh", ..., extra_claims={"jti": ...})` |
| Session cookie (`django.contrib.auth`) | bearer tokens; no cookies, no CSRF surface |
| Token blacklist app | Redis JTI whitelist (`auth/04`) |

Rolling your own JWT layer is a legitimate teaching choice here precisely
because it makes every claim and check visible. In production, a vetted library
abstraction (or `pyjwt` with the same discipline) is fine — the invariants are:
pin the algorithm, check `type`, short access TTL, stateful refresh.

## Production perspective

- **Key rotation**: with one HS256 secret, rotation requires accepting old+new
  during a window. Upgrade path: kid header + a key list in `decode_token`.
- **Token size**: access tokens are small (~200 bytes); no PII beyond `sub` —
  deliberately, since payloads are readable by anyone (only *signature* is
  protected).
- **Never put secrets in claims** — JWT payloads are base64, not encrypted.
- **`exp` enforcement** is PyJWT's job; do not hand-roll time checks.

## Common mistakes

1. **Omitting `algorithms=[...]`** in decode — accepts attacker-chosen
   algorithms in vulnerable libraries.
2. **Putting the user's email/role in the token** and trusting it for
   authorization — TeamFlow resolves roles **server-side from the DB** on every
   request (`auth/06-rbac.md`); the token carries only identity.
3. **Long-lived access tokens** — revocation lag becomes the session lifetime.
4. **Verifying `type` in some places but not others** — TeamFlow's documented
   gap; consistency is the rule.
5. **Using the same secret across environments** — a leaked dev secret must not
   sign prod tokens.

## Cheat sheet

```python
payload = {"sub": str(user.id), "type": "access", "iat": now, "exp": now + ttl}
jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])  # raises PyJWTError
```

## Review questions

1. Why is `algorithms=[...]` non-negotiable in `jwt.decode`?
2. Which claims does TeamFlow use for authorization, and where does authorization
   actually get its data?
3. Identify the three token-verification sites and which ones check `type`.
4. What exactly does a refresh-token-as-access-token attack gain an attacker,
   given the documented gap?
