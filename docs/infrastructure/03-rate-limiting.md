# Infrastructure 03 — Rate Limiting

## Concept

Rate limiting bounds how often a client may hit sensitive endpoints. TeamFlow
uses a **sliding window** over a Redis sorted set, keyed by (scope, identity).

## Why sliding window (not fixed window, not token bucket)

| Algorithm | Burst at boundary | Memory | TeamFlow |
| --- | --- | --- | --- |
| Fixed window (INCR+EXPIRE) | yes — 2× limit across the boundary | 1 counter | rejected |
| Sliding window (ZSET) | no — counts the last N seconds exactly | 1 member per hit | **chosen** |
| Token bucket | allows controlled burst | 2 values | not needed |

The boundary-burst problem is concrete: with a 5/min fixed window, a client can
send 5 at 11:59:59 and 5 at 12:00:00 — 10 in one second. The sliding window
counts actual hits in the last 60s, so that burst is impossible.

## Implementation — `app/core/rate_limit.py`

```python
async def hit_rate_limit(redis_client, scope, identity, max_hits, window_seconds) -> None:
    now = time.time()
    key = f"teamflow:rl:{scope}:{identity}"
    member = f"{now:.6f}:{secrets.token_hex(4)}"
    window_start = now - window_seconds
    try:
        pipe = redis_client.pipeline()
        pipe.zadd(key, {member: now})
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zcard(key)
        pipe.expire(key, window_seconds + 1)
        _, _, count, _ = await pipe.execute()
    except redis.RedisError:
        return  # fail open; Redis outage must not brick auth

    if int(count) > max_hits:
        oldest = await redis_client.zrange(key, 0, 0, withscores=True)
        retry_after = max(1, int(window_seconds - (now - oldest[0][1]))) if oldest else window_seconds
        raise RateLimitError(detail="Too many requests; slow down", retry_after=retry_after)
```

Line by line:

- **`member = f"{now}:{token_hex}"`** — unique member per hit (timestamp alone
  can collide in the same microsecond under load; the random suffix guarantees
  distinct ZSET members).
- **Pipeline executes as one round trip**: ZADD (record), ZREMRANGEBYSCORE
  (evict old), ZCARD (count), EXPIRE (cleanup). The count *includes* the
  current hit — the check is `count > max_hits`, so exactly `max_hits` requests
  pass.
- **`EXPIRE window+1`** — a window that goes quiet self-cleans; no sweeper.
- **Fail open on `RedisError`** — with a logged-away exception and a `return`.
  Availability of login beats throttling during a Redis outage (and auth still
  requires valid credentials).
- **`Retry-After` derived from the oldest hit** — tells the client exactly how
  long until a slot frees.

## Identity choice — the security design

```python
def ip_rate_limiter(scope, max_hits=None, window=None):
    async def _limit(request: Request, redis_client: RedisDep) -> None:
        if not settings.rate_limit_enabled:
            return
        await hit_rate_limit(redis_client, scope, client_ip(request), max_hits, window)
    return _limit

def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
```

- **Per-IP** protects anonymous endpoints (register, forgot-password) from
  volume abuse.
- **Per-email** (inside `auth.login`):

```python
await hit_rate_limit(redis, "auth_email", email.lower(),
                     settings.auth_rate_limit_max, settings.auth_rate_limit_window)
```

  Without it, an attacker on many IPs could brute-force one account; with
  per-email limits, the victim's account is protected regardless of source IP.
  And per-IP alone would let one attacker exhaust the quota *for* a victim
  (denial of login) — the email key separates identities.

- **Only the immediate socket IP is trusted.** `client_ip` deliberately ignores
  `X-Forwarded-For` (a client-controlled header). Behind a trusted proxy you
  would enable proxy-header parsing in uvicorn/gunicorn
  (`--proxy-headers --forwarded-allow-ips`), which TeamFlow documents rather
  than spoofing.

## Scopes and budgets

| Scope | Identity | Limit | Window | Endpoints |
| --- | --- | --- | --- | --- |
| `auth_ip` | IP | 5 | 60s | login |
| `auth_email` | email (lowered) | 5 | 60s | login (in service) |
| `register` | IP | 3 | 3600s | register |
| `password_reset` | IP | 3 | 3600s | forgot + reset |

`RATE_LIMIT_ENABLED=false` is the test-suite default (deterministic tests);
rate-limit tests flip it on (`tests/integration/test_rate_limiting.py`).

## Failure semantics

| Situation | Behavior |
| --- | --- |
| Redis down | fail open (logged); auth remains available |
| Limit exceeded | 429 + `Retry-After` |
| Different scopes | independent windows (login flood doesn't lock registration) |
| Successful + failed logins | both count (the check precedes verification) |

## Django/DRF comparison 🔵

| DRF | TeamFlow |
| --- | --- |
| `AnonRateThrottle` / `UserRateThrottle` (cache-backed, fixed window) | sliding ZSET, per-scope + per-email |
| `DEFAULT_THROTTLE_RATES = {"anon": "5/min"}` | dependency factories with explicit budgets |
| 429 with `retry-after` | same, derived from the oldest hit |
| Throttles configured globally per view class | declared per route in the signature |

DRF throttling is global-ish and cache-backend-agnostic (so it inherits the
fixed-window implementation of whatever cache you use). TeamFlow's explicit
sliding window in Redis is stricter and observable (`ZCARD` per key).

## Production perspective

- **Cost**: one pipelined round trip per guarded request — negligible, and only
  on sensitive endpoints.
- **Memory**: one ZSET member per hit within the window; bounded by
  `max_hits × identities`.
- **Distributed correctness**: the pipeline is atomic, and state lives in
  Redis, so limits hold across workers and restarts (until window expiry).
- **Known limits**: a Redis flush resets windows (abuse window opens); a
  distributed attacker with many IPs can still spread per-email attempts (that
  is where per-email helps most). No global/IP-blocklist layer exists — noted
  as an upgrade path (fail2ban-style banning at nginx).

## Common mistakes

1. **Fixed windows with burst at the boundary** — the reason for ZSETs.
2. **Rate limiting only by IP** — distributed brute force and lockout-by-proxy
   problems.
3. **Failing closed on Redis errors** — a Redis blip becomes a login outage.
4. **Trusting `X-Forwarded-For` from clients** — spoofable identity. Parse proxy
   headers only behind a trusted proxy.
5. **Forgetting to test with the limiter enabled** — TeamFlow's tests flip
   `settings.rate_limit_enabled` on for the limiter suite and off elsewhere.

## Cheat sheet

```
key:    teamflow:rl:{scope}:{identity}
hit:    ZADD member=now:rand | ZREMRANGEBYSCORE -inf now-window | ZCARD | EXPIRE
limit:  count > max → 429 Retry-After=window-(now-oldest)
redis down → fail open
```

## Review questions

1. Why does per-email limiting coexist with per-IP limiting on login?
2. Why is the current hit added *before* the count is read?
3. What exactly is protected by failing open, and what is the compensating
   control?
4. Why does `client_ip` ignore `X-Forwarded-For`, and what would you change in
   the deployment to safely use it?
