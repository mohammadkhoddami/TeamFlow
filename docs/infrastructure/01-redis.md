# Infrastructure 01 — Redis

## Concept

Redis is an in-memory data store used in TeamFlow for four things — each with a
distinct reason. Redis is never a **source of truth**; everything in it is
either reconstructible (caches) or intentionally ephemeral (rate limits, token
whitelist).

## The four uses (and the reason for each)

| Use | Key pattern | Why Redis | If Redis is down |
| --- | --- | --- | --- |
| Refresh-token whitelist | `teamflow:rt:{user}:{jti}` | TTL-native, sub-ms refresh path, no cleanup job | refresh fails closed → users re-login |
| Rate limiting | `teamflow:rl:{scope}:{identity}` | atomic sorted-set ops, shared across workers | **fail open** (requests proceed) |
| WebSocket pub/sub | `teamflow:ws` (channel) | cross-worker fan-out without sticky sessions | realtime degrades; API fine |
| Dashboard cache | `teamflow:cache:dashboard:{org}` | absorbs repeated polling | falls back to SQL (correct, slower) |

The design rule: **every use has a documented degradation mode**. None of them
can take down the API.

## The client — `app/core/redis.py`

```python
_client: Redis | None = None

def get_redis_client() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True,
                                 socket_connect_timeout=2, socket_timeout=2,
                                 health_check_interval=30)
    return _client

async def close_redis_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
```

- One client per process (connection pool inside), created lazily, closed in
  the lifespan.
- `socket_*_timeout=2` — a hung Redis must not hang requests; 2s bounds the
  damage.
- `decode_responses=True` — str ergonomics (TeamFlow stores only simple values).
- Dependency exposure: `RedisDep = Annotated[Redis, Depends(get_redis_client)]`.

## Key naming

```
teamflow:rt:{user_id}:{jti}          refresh token whitelist
teamflow:prt:{sha256(token)}          password-reset tokens (hashed at rest)
teamflow:rl:{scope}:{email|ip}        rate limit windows
teamflow:cache:dashboard:{org_id}     dashboard cache
teamflow:ws                            pub/sub channel
```

Prefixing by purpose makes the keyspace auditable (`redis-cli --scan --pattern
'teamflow:*'`), enables per-purpose eviction policies later, and makes bugs
obvious ("why is a cache key under `rt:`?").

## Failure handling patterns (copy these)

### Fail open — rate limiting

```python
try:
    _, _, count, _ = await pipe.execute()
except redis.RedisError:
    return  # fail open; Redis outage must not brick auth
```

Rationale: rate limits protect against abuse, not against availability risks
created by the protection itself. A Redis outage should not lock out login.

### Fail closed — refresh tokens

A missing JTI is indistinguishable from a revoked one, so refresh fails with
reuse-detection semantics and forces re-login. For a *security* store, failing
closed is correct.

### Degrade to the database — dashboard cache

```python
async def get_dashboard_cache(redis_client, organization_id) -> dict | None:
    try:
        raw = await redis_client.get(dashboard_key(organization_id))
        return json.loads(raw) if raw else None
    except (redis.RedisError, ValueError):
        return None
```

A cache miss and a Redis outage take the same path: recompute. No error
surfaces.

### Log and continue — WebSocket publish

```python
try:
    await get_redis_client().publish(WS_CHANNEL, json.dumps(payload))
except Exception:
    logger.exception("Failed to publish realtime event %s", event_type)
```

Realtime is best-effort; the HTTP request that triggered it must not fail.

## Multi-worker semantics

Every Redis use is shared across processes by construction:

- rate limits: one window per (scope, identity) regardless of which worker
  accepts the request;
- token whitelist: login on worker A, refresh on worker B works;
- pub/sub: published by any worker, delivered by every listener;
- cache: first dashboard hit warms it for all workers.

This is the main reason TeamFlow uses Redis at all: **it is the shared-state
substrate for a horizontally scaled process fleet**.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `django.core.cache` (framework abstraction) | direct `redis.asyncio` client (explicit keys, explicit TTL) |
| `django-redis` session backend | refresh-token whitelist (purpose-built, not sessions) |
| DRF throttling (`cache`-backed) | sorted-set sliding window |
| Channels channel layer | raw pub/sub + listener |
| `django-celery-results` | Celery result backend (configured, barely used) |

Django hides Redis behind framework interfaces; TeamFlow keeps it explicit
because the *semantics* differ per use (fail open vs closed vs degrade) — an
abstraction that unified them would obscure exactly what matters.

## Production perspective

- **Persistence**: compose runs `redis-server --appendonly yes` —
  needed so a restart doesn't log everyone out (refresh whitelist).
- **Memory policy**: with AOF and no `maxmemory`, Redis grows only with
  rate-limit windows, token whitelists, and one dashboard key per org. All have
  TTLs, so usage is bounded by design.
- **Restart blast radius**: rate limits reset (harmless), cache cold (busy
  dashboards recompute), refresh tokens intact with AOF, WS clients reconnect
  to a live listener (reconnect loop in `run_redis_listener`).
- **Scaling path**: Redis Cluster / Sentinel — the client accepts a URL; keys
  are independent, no cross-key transactions are used.

## Common mistakes

1. **Using Redis as a database.** TeamFlow stores only ephemeral/derived data.
   If Redis is flushed, the system is *functionally* intact.
2. **No TTLs.** Every key here has one (`ex=`); leaks are impossible.
3. **Unbounded `KEYS`.** `revoke_all_refresh_tokens` uses `scan_iter`.
4. **Blocking the loop with a sync Redis client in the API.** TeamFlow uses
   `redis.asyncio` everywhere in the API; workers use the sync client only for
   a one-off cache warm.
5. **Assuming Redis holds state across workers** but keying by something
   process-local (e.g., in-memory user id) — keys must be globally meaningful.

## Cheat sheet

```
refresh:  SET teamflow:rt:{u}:{jti} 1 EX 14d | EXISTS | DEL | SCAN+DEL
reset:    SET teamflow:prt:{sha256} {uid} EX 30m | GETDEL
ratelimit:SADD/ZREM/ZCARD ZSET EX window (fail open)
cache:    SET teamflow:cache:dashboard:{org} json EX 60
pubsub:   PUBLISH teamflow:ws payload
```

## Review questions

1. For each of the four Redis uses, state the degradation mode and why it was
   chosen.
2. Why is the refresh whitelist fail-closed while rate limiting is fail-open?
3. Why does `decode_responses=True` matter for the WS listener?
4. What does AOF persistence protect in this design, and what is acceptable to
   lose on a Redis flush?
