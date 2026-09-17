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

from redis.asyncio import Redis

RT_PREFIX = "teamflow:rt"
RESET_PREFIX = "teamflow:prt"


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
    import hashlib

    digest = hashlib.sha256(token.encode()).hexdigest()
    await redis.set(f"{RESET_PREFIX}:{digest}", user_id, ex=ttl_seconds)


async def consume_password_reset_token(redis: Redis, token: str) -> str | None:
    """Atomic single-use: GETDEL so a token can never be redeemed twice."""
    import hashlib

    digest = hashlib.sha256(token.encode()).hexdigest()
    return await redis.getdel(f"{RESET_PREFIX}:{digest}")
