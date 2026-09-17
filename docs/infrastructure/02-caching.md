# Infrastructure 02 — Caching

## Concept

Caching stores a computed result so repeated reads skip the computation. The
hard parts are not storing — they are **invalidation**, **TTL choice**, and
**failure behavior**.

## What TeamFlow caches (and nothing else)

Only the **dashboard statistics**:

```
teamflow:cache:dashboard:{org_id} → JSON stats, TTL 60s
```

Why only this?

| Candidate | Cached? | Reason |
| --- | --- | --- |
| Dashboard stats | ✅ | 5 aggregate queries per hit; polled repeatedly by every dashboard viewer |
| Task lists | ❌ | change constantly; invalidation would exceed hit rate |
| Org members | ❌ | one indexed query, small |
| User profile | ❌ | one PK lookup |
| Refresh tokens | ✅ (but not a cache) | it's a whitelist store, not derived data |

The discipline: cache what is (a) expensive to compute, (b) read often, and
(c) tolerant of brief staleness.

## Implementation — `app/services/cache.py`

```python
DASHBOARD_TTL_SECONDS = 60

def dashboard_key(organization_id: uuid.UUID) -> str:
    return f"teamflow:cache:dashboard:{organization_id}"

async def get_dashboard_cache(redis_client, organization_id) -> dict | None:
    try:
        raw = await redis_client.get(dashboard_key(organization_id))
        return json.loads(raw) if raw else None
    except (redis.RedisError, ValueError):
        return None

async def set_dashboard_cache(redis_client, organization_id, stats) -> None:
    try:
        await redis_client.set(dashboard_key(organization_id),
                               json.dumps(stats, default=str),
                               ex=DASHBOARD_TTL_SECONDS)
    except redis.RedisError:
        logger.warning("Dashboard cache write failed (Redis down?); serving uncached")

async def invalidate_dashboard(organization_id) -> None:
    try:
        await get_redis_client().delete(dashboard_key(organization_id))
    except redis.RedisError:
        logger.warning("Dashboard cache invalidation failed (Redis down?)")
```

Three properties worth copying:

1. **Every operation is failure-tolerant.** Cache is an optimization; the code
   must never fail because of it.
2. **The key embeds the tenant** — a cache key without `org_id` would be a
   cross-tenant data leak (the cached-read version of IDOR).
3. **`default=str` on `json.dumps`** — stats contain UUIDs/datetimes; the
   serializer handles them without a custom encoder.

## Read path — `app/services/dashboard.py`

```python
async def get_dashboard(db, redis_client, organization_id, *, use_cache=True) -> dict:
    if use_cache:
        cached = await cache.get_dashboard_cache(redis_client, organization_id)
        if cached is not None:
            return cached
    stats = await compute_stats(db, organization_id)
    await cache.set_dashboard_cache(redis_client, organization_id, stats)
    return stats
```

- Cache-aside (lazy population): first hit computes and stores, later hits read.
- `?use_cache=false` on the route forces recomputation — a debugging affordance
  that also serves tests (`tests/integration/test_dashboard_cache.py`).

## Invalidation — explicit, not TTL-only

Mutations call `cache.invalidate_dashboard(org_id)`. The complete, greppable set:

| Mutation | File | Invalidates? |
| --- | --- | --- |
| task create / update / delete | `app/services/tasks.py` (3 call sites) | ✅ |
| project update / delete | `app/services/projects.py` | ✅ |
| **project create** | `app/services/projects.py` | ❌ stale ≤60s (project counts) |
| **membership add/remove, invitation accept** | `organizations.py`, `invitations.py` | ❌ stale ≤60s (`active_members`) |
| task label link changes | via `tasks.update_task` | ✅ (delegates) |

⚠️ **Honest audit** — the invalidation map is incomplete in two places, and the
TTL is what bounds them. The grep is the review procedure:

```bash
grep -rn "invalidate_dashboard" app/services/
```

Any mutating service that changes a dashboard number and is *not* on this list
either needs a call or an explicit "we accept ≤60s staleness here" note. This
is the correct way a tolerant cache degrades: **bounded staleness, documented**.

## Why invalidation-before-TTL matters

If only the TTL existed, a user completing a task would see stale counts for up
to 60s. Explicit invalidation makes the common case immediate while the TTL
still protects against missed invalidations (employees of the two gaps above,
plus any future worker path that mutates data). This is the standard "TTL as
safety net, invalidation as mechanism" pairing.

## Dashboard aggregation cost (what we're saving)

`compute_stats` runs 5 SQL aggregates (`database/04-queries.md`). At a few
thousand tasks that's a few milliseconds — but a dashboard page polls, and every
viewer polls. The cache converts N viewers × M polls into ~1 compute per minute
per org.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `cache.get/set` + `cache_page` decorator | explicit `cache.py` helpers |
| `KEY_PREFIX`/`VERSION` settings | tenant id embedded in the key |
| `post_save` signal invalidating cache | explicit `invalidate_dashboard` calls in services |
| `CACHE_TTL` setting | constant + per-call `ex=` |
| `django-cachalot` (queryset cache) | not used — correctness > magic |

Django's `post_save`-driven invalidation is implicit (you hope every mutation
fires it). TeamFlow's explicit calls are greppable and reviewable — the same
philosophy as explicit side effects in services.

## Production perspective

- **Thundering herd**: on a cold cache, concurrent dashboard hits may all
  compute (no lock). With 5 fast queries, acceptable. At scale, a short
  `SET NX` lock or stale-while-revalidate would smooth it.
- **Cache stampede on deploy**: Redis keys survive deploys, so caches stay warm.
- **Serialization drift**: the cached JSON is re-validated by
  `DashboardStats.model_validate(stats)` at the route — schema changes fail
  loudly rather than silently serving old shapes (worth a `VERSION` in the key
  if this ever bites).
- **Memory**: one key per active org, ≤1KB, 60s TTL — bounded and tiny.

## Common mistakes

1. **Caching user-specific data under a shared key** — cross-tenant leak. Keys
   must include the tenant/user.
2. **No error handling around Redis in the read path** — a cache outage becomes
   a site outage.
3. **Caching without invalidation and calling the TTL "eventual consistency"** —
   acceptable only if you can state the acceptable staleness window.
4. **Caching mutable ORM objects** — serialize to JSON/dict; never store model
   instances.
5. **Forgetting `default=str`** and crashing on UUID serialization.

## Cheat sheet

```
read:  try cache → miss → compute → set(ex=60) → return
write: mutate → commit → invalidate_dashboard(org_id)
key:   teamflow:cache:dashboard:{tenant_id}
```

## Review questions

1. Why is the dashboard the only cached resource?
2. What are the two mechanisms keeping dashboard stats fresh, and which one is
   the "mechanism" vs the "safety net"?
3. What would break if the cache key omitted `org_id`?
4. Where would you add invalidation if `projects.create` changes stats? (Check
   whether it already does.)
