"""Redis-backed token lifecycle store.

Refresh tokens are JWTs but *stateful*: their `jti` is whitelisted here with a
TTL matching token expiry. This is what makes logout and rotation real:
  - rotation: refresh consumes the old jti and issues a new one
  - reuse detection: presenting a jti that is no longer whitelisted revokes the
    whole session family (a replayed stolen token burns every child token)
  - logout: deletes the jti; logout_all: sweeps all of a user's refresh tokens

Access tokens remain stateless short-lived JWTs (30 min) — invalidating them
per-request would cost a Redis hit on every API call, which we reject for
latency; logout documents that access tokens die within their short TTL.
"""

import hashlib
import hmac
import json

from redis.asyncio import Redis

from app.core.config import settings

RT_PREFIX = "teamflow:rt"
RESET_PREFIX = "teamflow:prt"
OTP_PREFIX = "teamflow:otp"
OAUTH_STATE_PREFIX = "teamflow:oauth:state"
OAUTH_CODE_PREFIX = "teamflow:oauth:code"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _peppered(value: str) -> str:
    """HMAC with the app secret: a Redis leak alone cannot brute-force the
    6-digit OTP space offline (plain SHA-256 could be inverted instantly)."""
    return hmac.new(
        settings.secret_key.encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def refresh_key(user_id: str, jti: str) -> str:
    return f"{RT_PREFIX}:{user_id}:{jti}"


async def store_refresh_token(
    redis: Redis, user_id: str, jti: str, ttl_seconds: int
) -> None:
    await redis.set(refresh_key(user_id, jti), "1", ex=ttl_seconds)


async def is_refresh_token_active(redis: Redis, user_id: str, jti: str) -> bool:
    return await redis.exists(refresh_key(user_id, jti)) == 1


async def revoke_refresh_token(redis: Redis, user_id: str, jti: str) -> None:
    await redis.delete(refresh_key(user_id, jti))


async def revoke_all_refresh_tokens(redis: Redis, user_id: str) -> int:
    pattern = f"{RT_PREFIX}:{user_id}:*"
    deleted = 0
    async for key in redis.scan_iter(match=pattern, count=100):
        await redis.delete(key)
        deleted += 1
    return deleted


async def store_password_reset_token(
    redis: Redis, token: str, user_id: str, ttl_seconds: int
) -> None:
    await redis.set(f"{RESET_PREFIX}:{_sha256(token)}", user_id, ex=ttl_seconds)


async def consume_password_reset_token(redis: Redis, token: str) -> str | None:
    """Atomic single-use: GETDEL so a token can never be redeemed twice."""
    return await redis.getdel(f"{RESET_PREFIX}:{_sha256(token)}")


# ------------------------------------------------------------------ email OTP


def otp_key(email: str) -> str:
    return f"{OTP_PREFIX}:{email.lower()}"


def otp_attempts_key(email: str) -> str:
    return f"{OTP_PREFIX}:attempts:{email.lower()}"


async def store_otp(redis: Redis, email: str, code: str, ttl_seconds: int) -> None:
    """One active code per email; a fresh request resets the attempt budget."""
    await redis.delete(otp_attempts_key(email))
    await redis.set(otp_key(email), _peppered(code), ex=ttl_seconds)


async def verify_otp(redis: Redis, email: str, code: str, max_attempts: int) -> bool:
    """Single-use verification with a wrong-attempt cap. A correct code burns
    the stored value; too many wrong tries burns the code itself."""
    stored = await redis.get(otp_key(email))
    if not stored:
        return False

    attempts = await redis.incr(otp_attempts_key(email))
    if attempts == 1:
        await redis.expire(otp_attempts_key(email), settings.otp_ttl_seconds)
    if attempts > max_attempts:
        await redis.delete(otp_key(email), otp_attempts_key(email))
        return False

    if not hmac.compare_digest(stored, _peppered(code)):
        return False
    await redis.delete(otp_key(email), otp_attempts_key(email))
    return True


# ------------------------------------------------------- OAuth login hand-off


async def store_oauth_state(
    redis: Redis, state: str, payload: dict[str, str], ttl_seconds: int
) -> None:
    await redis.set(f"{OAUTH_STATE_PREFIX}:{state}", json.dumps(payload), ex=ttl_seconds)


async def consume_oauth_state(redis: Redis, state: str) -> dict[str, str] | None:
    """Atomic single-use so a replayed callback can never mint a second login."""
    raw = await redis.getdel(f"{OAUTH_STATE_PREFIX}:{state}")
    return json.loads(raw) if raw else None


async def store_oauth_login_code(
    redis: Redis, code: str, user_id: str, ttl_seconds: int
) -> None:
    await redis.set(f"{OAUTH_CODE_PREFIX}:{_sha256(code)}", user_id, ex=ttl_seconds)


async def consume_oauth_login_code(redis: Redis, code: str) -> str | None:
    return await redis.getdel(f"{OAUTH_CODE_PREFIX}:{_sha256(code)}")
