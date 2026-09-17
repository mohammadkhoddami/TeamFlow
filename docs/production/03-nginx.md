# Production 03 — Nginx

## Concept

Nginx is the edge: TLS termination (future), routing to the API, WebSocket
upgrade handling, and a body-size cap. TeamFlow ships a minimal config that
teaches the shape without over-engineering.

## The config — `deploy/nginx.conf`

```nginx
upstream teamflow_api {
    server api:8000;
    keepalive 32;
}

server {
    listen 80;
    server_name _;

    # Real deployments add HSTS + TLS certs here.
    client_max_body_size 12m;          # 10 MB app cap + envelope overhead

    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 75s;            # > WS keepalive intervals

    location /ws/ {
        proxy_pass http://teamflow_api;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location / {
        proxy_pass http://teamflow_api;
    }

    location /api/v1/health/live {
        proxy_pass http://teamflow_api;
        access_log off;
    }
}
```

## Why each directive exists

| Directive | Problem it solves |
| --- | --- |
| `upstream ... keepalive 32` | reuse backend connections instead of a new TCP handshake per proxied request |
| `client_max_body_size 12m` | rejects oversized bodies at the edge (defense in depth vs the app's 10 MB cap) |
| `proxy_http_version 1.1` | required for `Upgrade`/keepalive semantics |
| `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto` | the API/handlers can know the original request context; TLS termination makes `$scheme` important |
| `location /ws/` + `Upgrade`/`Connection` headers | without these, WebSocket handshakes fail through the proxy |
| `proxy_read_timeout 75s` | long-lived WS connections must not be killed by the default 60s timeout |
| health `access_log off` | probe traffic doesn't flood logs |

## The `X-Forwarded-For` detail (and TeamFlow's stance)

Nginx sets `X-Forwarded-For` correctly for well-behaved clients. But the app's
`client_ip()` (`app/core/rate_limit.py`) deliberately ignores that header:

```python
def client_ip(request: Request) -> str:
    """Only the immediate socket IP is trusted. Honoring X-Forwarded-For blindly
    would let callers spoof others' limits (set PROXY_TRUSTED deployment-level
    instead if behind a trusted proxy)."""
    return request.client.host if request.client else "unknown"
```

To actually use the forwarded IP in production you enable proxy-header parsing
at the **server** level, where the trust boundary is explicit:

```bash
gunicorn ... --forwarded-allow-ips="<nginx-ip>"   # uvicorn: --proxy-headers
```

Then `request.client.host` becomes the client IP. The lesson: *who is allowed
to set the forwarded header* is a deployment decision, not application logic.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| nginx in front of gunicorn (same shape) | nginx in front of gunicorn+uvicorn |
| `proxy_set_header` blocks copied from a wiki | same, but each line justified above |
| `client_max_body_size` vs `DATA_UPLOAD_MAX_MEMORY_SIZE` | edge cap + app cap (12m vs 10 MB) |
| WS via daphne/channels behind nginx | WS via uvicorn workers behind nginx (same upgrade headers) |

Nothing Django-specific hides here — the edge layer is framework-agnostic. The
only FastAPI-specific bit is that the same gunicorn process serves both HTTP
and WS, so one location block pair covers both.

## Production perspective

- **TLS terminates here** in real deployments; the app never sees certificates.
- **`X-Forwarded-Proto`** matters for generating absolute URLs (TeamFlow uses
  `settings.frontend_base_url` for reset links instead, avoiding the
  dependency).
- **Rate limiting at the edge** (nginx `limit_req`) is the next layer above
  TeamFlow's Redis limiter: cheap early rejection before the request reaches
  Python. Not configured here; noted in `production/07-security.md`.
- **Scaling**: add `server` entries to the upstream block; no sticky sessions
  needed (stateless API + Redis-backed realtime).

## Common mistakes

1. **Forgetting the WS `Upgrade`/`Connection` headers** — sockets 400/close
   immediately through the proxy.
2. **Default `proxy_read_timeout`** killing idle WebSockets.
3. **Trusting `X-Forwarded-For` from the internet** — spoofable; only trust it
   from a known proxy.
4. **`client_max_body_size` smaller than the app's limit** — the app's clean 422
   becomes an nginx 413 with a different body shape.
5. **Serving `/docs` publicly by accident** — deliberate decision now
   (`production/07`).

## Review questions

1. Which directive makes WebSockets work, and what breaks without it?
2. Why does `client_max_body_size` (12m) exceed the app's upload cap (10 MB)?
3. Why does TeamFlow ignore `X-Forwarded-For` by default, and what must be true
   before trusting it?
4. Where would you add TLS, and what changes in the application (if anything)?
