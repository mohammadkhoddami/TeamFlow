# Auth 02 — Password Hashing

## Concept

Passwords are never stored — only a one-way hash with a per-password random
salt. Verification re-hashes the attempt and compares. TeamFlow uses bcrypt via
`passlib`.

## Why it exists

If the database leaks, attackers must not be able to recover passwords. bcrypt
is deliberately slow (tunable cost factor), making offline brute force
expensive, and its salt prevents rainbow-table/identical-hash analysis.

## TeamFlow implementation — `app/core/security.py`

```python
# bcrypt is deliberately capped below 4.1 because passlib 1.7.4 mis-handles
# the 72-byte hash truncation change in bcrypt 4.1+.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)
```

Details a reviewer must know:

- **Why passlib + pinned bcrypt**: passlib 1.7.4 (latest) reads bcrypt's
  version string in a way bcrypt ≥4.1 broke; the pin `bcrypt<4.1` in
  `pyproject.toml` is load-bearing, not cosmetic. The dependency trio
  (`passlib[bcrypt]`, `bcrypt<4.1`) is a known ecosystem wart.
- **`deprecated="auto"`** means passlib will flag hashes produced by older
  schemes for re-hash-on-login if the scheme list ever changes. The hook exists;
  the re-hash logic isn't implemented (no scheme migration has happened).
- **Salting is automatic** — bcrypt embeds a random salt in the output string
  (`$2b$12$...`), so two users with the same password get different hashes.
  `tests/unit/test_security_helpers.py` asserts exactly that.
- **Cost factor 12** (bcrypt default in passlib) ≈ 100–250ms per hash on
  commodity hardware — the deliberate slowness. It also means **hashing is
  blocking CPU work** (`async/03-blocking-vs-nonblocking.md`).

## Password policy

```python
# app/schemas/auth.py
class UserCreate(SQLModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
```

- Minimum 10 characters — a policy choice enforced at the API edge (before any
  hashing work).
- Maximum 128 — bcrypt truncates/errors past 72 **bytes**; a bound prevents
  surprise behavior and oversized payloads. (Strictly, the 72-byte limit should
  be enforced in bytes, not characters — a noted edge case for non-ASCII
  passwords; see `production/07-security.md`.)

## Where passwords appear (and don't)

| Location | Password present? |
| --- | --- |
| `UserCreate` request schema | yes (plaintext in memory) |
| `auth.register_user` | yes → immediately hashed |
| `users.hashed_password` column | hash only |
| Audit log `meta` | **email only**, never the password |
| Login request (OAuth2 form) | plaintext in memory, verified, discarded |
| `UserRead` response schema | no field exists |
| Reset flow | new password hashed in `reset_password`; token single-use |

## Reset flow's hashing duties

`app/services/auth.py`:

```python
async def reset_password(db, redis, data: PasswordReset, ip=None) -> None:
    user_id = await token_store.consume_password_reset_token(redis, data.token)
    if not user_id:
        raise UnauthorizedError("Invalid or expired reset token")

    user = await UserRepository(db).get(uuid.UUID(user_id))
    if not user:
        raise NotFoundError("User not found")

    user.hashed_password = security.hash_password(data.new_password)
    await UserRepository(db).update(user)
    await token_store.revoke_all_refresh_tokens(redis, user_id)   # kill sessions
    await audit.log(db, AuditAction.PASSWORD_RESET, actor_id=user.id, ip=ip,
                    meta={"email": user.email})
    await db.commit()
```

Two behaviors worth teaching:

- **Reset revokes every refresh token** — a password change is treated as a
  full logout (standard practice).
- **Reset tokens are single-use and hashed at rest** in Redis
  (`token_store.consume_password_reset_token` uses `GETDEL` on a SHA-256 digest)
  — a Redis dump doesn't reveal usable tokens, and there is no replay window.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `make_password` / `check_password` | `hash_password` / `verify_password` (passlib) |
| `bcrypt` / `argon2` via `PASSWORD_HASHERS` | passlib `CryptContext(schemes=["bcrypt"])` |
| `AUTH_PASSWORD_VALIDATORS` settings | Pydantic `min_length`/`max_length` (plus rate limits) |
| Re-hash on login (Django does this automatically) | not implemented (no scheme migration yet) |
| Password reset tokens via `django.contrib.auth` | Redis single-use tokens + Celery email |

Django's password validation framework is richer (common-password lists,
similarity checks). TeamFlow has length bounds + rate limiting — honest scope
note in `mastery/10-what-i-actually-master.md`.

## Production perspective

- **Bcrypt is CPU-blocking (~100ms+).** On the login endpoint this is
  acceptable: rate limits bound abuse and logins are infrequent per user. If
  logins ever become a hot path, move hashing to a threadpool
  (`await run_in_threadpool(hash_password, pw)`) — noted as the pattern, not
  currently needed.
- **Cost factor tuning** is a latency/security dial: 12 is a reasonable 2020s
  default. Raising it requires re-hashing on next login (the `deprecated`
  hook).
- **Never log hashes.** Even hashes in logs are a gift to attackers (offline
  cracking). TeamFlow's audit meta records emails only.

## Common mistakes

1. **`md5`/`sha256(password)` DIY hashing** — fast hashes are useless against
   GPUs. Use bcrypt/argon2.
2. **Storing the hash in the same serializer as the response model** — caused
   by reusing one schema for DB and API (TeamFlow separates them).
3. **Forgetting the bcrypt version pin** — passlib starts raising
   `AttributeError`/hash failures on newer bcrypt; the comment in the code is
   there for a reason.
4. **Password in logs or audit metadata** — none in TeamFlow; check any new
   audit call you review.
5. **Comparing hashes with `==`** in custom code — use the library's
   constant-time verify.

## Cheat sheet

```python
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
hashed = pwd_context.hash(pw)          # salt included, cost 12
ok = pwd_context.verify(pw, hashed)    # constant-time
# never: store, log, or return `pw`
```

## Review questions

1. Where is the bcrypt version pin, and what happens if you remove it?
2. Why does registering two users with the same password produce different
   hashes?
3. Why does password reset revoke all refresh tokens?
4. What is the exact trade-off of bcrypt's cost factor, and where does TeamFlow
   deliberately accept that cost on the request path?
