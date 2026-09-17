# Production 07 — Security (Review)

This is a teaching-oriented security review of the actual implementation.
Format per finding: **Problem → Why it matters → How TeamFlow handles it →
What could go wrong → How to improve it.**

## What TeamFlow gets right (verified in code and tests)

| Control | Where |
| --- | --- |
| bcrypt password hashing with pinned version | `app/core/security.py` |
| JWT algorithm pinning (`algorithms=[...]`) | `app/core/security.py` |
| Refresh rotation + reuse detection (family revocation) | `app/services/auth.py` |
| Single-use, hashed-at-rest password reset tokens (GETDEL) | `app/services/token_store.py` |
| Sliding-window rate limits (IP + email) with `Retry-After` | `app/core/rate_limit.py` |
| Tenant isolation: server-resolved membership, 404 doctrine | `app/api/deps.py`, services |
| IDOR-through-references blocked (assignee/label org checks) | `app/services/tasks.py` |
| Response-model allow-list (no `hashed_password` leaks) | `app/schemas/` |
| Upload allow-list + size cap + sanitized names + server keys | `app/services/attachments.py` |
| HMAC-signed webhooks with delivery-id dedupe | `app/services/integrations/webhook_signing.py` |
| Parameterized SQL everywhere; no string-built ORDER BY | repositories |
| Generic 500 bodies; stack traces only in logs | `app/core/exceptions.py` |
| Parameterized-query idempotency (unique claim) | `app/core/idempotency.py` |
| CORS allow-list + explicit headers | `app/main.py` |

## Findings (with severity)

### S1 — Access token type is not verified on HTTP requests

- **Problem**: `get_current_user` decodes the JWT and trusts `sub` without
  checking `payload["type"] == "access"` (`app/api/deps.py`). Refresh and
  WebSocket verification *do* check it.
- **Why it matters**: a refresh token (14-day TTL) is accepted as an access
  token — a stolen refresh token grants HTTP access far beyond 30 minutes.
- **What could go wrong**: token leakage impact is amplified from 30 min to
  14 days for every endpoint.
- **Fix**: one line — reject non-access types in `get_current_user`, and add a
  regression test asserting `POST /auth/refresh`'s token is rejected by
  `GET /auth/me`.

### S2 — SSRF via webhook URLs

- **Problem**: `AnyHttpUrl` validates shape only; internal addresses
  (`127.0.0.1`, `10.0.0.0/8`, `169.254.169.254` metadata) are accepted.
- **Why it matters**: an org admin can point deliveries at internal services or
  cloud metadata endpoints.
- **What could go wrong**: internal port scanning / metadata credential theft
  from the worker network position.
- **Fix**: resolve hostnames at delivery time and reject private CIDR ranges;
  optionally allow-list ports and route through an egress proxy. Document that
  `trust_env` proxying already exists and could host the enforcement.

### S3 — Default secrets boot in production

- **Problem**: `SECRET_KEY` has a dev default; nothing refuses to start with it
  when `ENVIRONMENT=production`.
- **Why it matters**: a deployment that forgets to inject the secret signs JWTs
  with a publicly-known value → full auth forgery.
- **Fix**: a `model_validator` on `Settings` that raises when
  `environment == "production"` and the secret is the default; same for empty
  S3/SMTP credentials.

### S4 — Bcrypt blocks the event loop (~100 ms per auth call)

- **Problem**: `hash_password`/`verify_password` run inline in async services.
- **Why it matters**: under credential-stuffing load, login workers stall other
  requests.
- **Mitigations already in place**: rate limits (5/min/email + IP) cap the
  attempt rate; auth endpoints are the only users.
- **Fix if needed**: `await run_in_threadpool(security.verify_password, ...)`.

### S5 — Upload content type is client-declared

- **Problem**: the allow-list trusts the declared `Content-Type`; bytes are not
  inspected (no magic-byte check; storage is presigned direct).
- **Why it matters**: an attacker can upload a script/HTML with an allowed
  declared type; if anything later serves it with a sniffable disposition, XSS
  is possible.
- **Mitigations**: bucket is private; downloads go through presigned URLs with
  the stored content type; browsers don't execute text/plain or images.
- **Fix**: post-upload verification job (magic bytes / AV scan) or proxy
  uploads for scan-sensitive tenants.

### S6 — Password policy is length-only; bcrypt's 72-byte limit is enforced by
characters

- **Problem**: `min_length=10/max_length=128` on characters; bcrypt truncates at
  72 **bytes** (multi-byte characters can exceed it).
- **Fix**: validate `len(password.encode("utf-8")) <= 72` or move to argon2.

### S7 — No ownership transfer; `is_superuser` is dead code

- **Problem**: owner is immutable by design (no handover flow); a reserved
  `is_superuser` flag exists but nothing consults it.
- **Why it matters**: operational dead-ends (orgs can't change owner) and a
  field that looks like a back door but isn't.
- **Fix**: implement ownership transfer (explicit endpoint) or document
  `is_superuser`'s intended future use and remove it until then.

### S8 — Logout revocation is bounded by the access-token TTL

- **Problem**: stateless access tokens stay valid ≤30 min after logout.
- **Why it matters**: "log out" doesn't immediately invalidate every credential.
- **Accepted trade-off** (documented in `auth/04`); strict needs would add a
  per-request revocation cache or token-version claim.

## Defense-in-depth recommendations (not implemented)

| Recommendation | Closes |
| --- | --- |
| Postgres RLS keyed on a session tenant variable | any future forgotten `organization_id` filter |
| nginx `limit_req` in front of auth paths | volumetric abuse before Python |
| A `CheckConstraint` on `memberships.role` | invalid role strings in data |
| Partial unique index on pending invitations | the documented invite race |
| Dependabot/`pip-audit` in CI | dependency CVEs (`bcrypt<4.1` pin is a known trade-off) |
| Secret scanning in CI | accidental `.env` commits |

## Prompt-injection / agentic note for reviewers

This project is reviewed by AI agents. The security posture above is only as
good as the review loop: the S1 gap existed through the entire build and was
substantially caught by *documenting assumptions*, not by a test. When
reviewing agent-generated auth code, always ask: **"which verification sites
check token type, and is that list complete?"** — consistency across call sites
is where gaps live.

## Review questions

1. Rank S1–S4 by severity for a production deployment and justify.
2. Why is S2 an "admin-trusted" issue but still worth fixing?
3. Which finding is a *design trade-off* rather than a bug, and what would the
   strict alternative cost?
4. Write the one-line fix and regression test for S1.
