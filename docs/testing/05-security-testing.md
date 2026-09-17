# Testing 05 — Security Testing

## Concept

Security tests assert the *negative space*: what must never happen. In TeamFlow
these are not a separate file but a deliberate half of the suite — every attack
surface from `auth/07-multi-tenancy.md` has an assertion behind it.

## The attack matrix and where it's asserted

### Tenant isolation / IDOR — `test_tasks.py`, `test_projects.py`, `test_organizations_rbac.py`

```python
async def test_task_tenant_isolation_idor(client, board):
    outsider = await make_user(client, email="task-outsider@example.com")
    OH = await auth_headers(outsider)
    assert (await client.get(f"/api/v1/tasks/{task['id']}", headers=OH)).status_code == 404
    assert (await client.patch(f"/api/v1/tasks/{task['id']}", json={"title": "hacked"}, headers=OH)).status_code == 404
    assert (await client.delete(f"/api/v1/tasks/{task['id']}", headers=OH)).status_code == 404
    assert (await client.get(f"/api/v1/tasks/{task['id']}/comments", headers=OH)).status_code == 404
    assert (await client.get(f"/api/v1/tasks/{uuid.uuid4()}", headers=await auth_headers(alice))).status_code == 404
```

Every id-addressed surface (task, project, org, comments, attachments, WS,
invitations) has this test. 404 uniformly — the suite also pins that non-members
do **not** receive 403 (which would confirm existence).

### Role restrictions — `test_organizations_rbac.py`

The suite walks the full rank matrix:

```python
# manager cannot promote member to admin
r = await client.patch(f".../members/{ids[MEMBER]}", json={"role": "admin"}, headers=await H(seeded["manager"]))
assert r.status_code == 403
# admin cannot touch the owner
# nobody can change their own role
# manager cannot demote the admin that outranks them
# member cannot invite; manager can invite member but not admin
```

### Authentication — `test_auth_flow.py`

| Assertion | Attack pinned |
| --- | --- |
| refresh reuse → 401 and *the new token dies too* | stolen-token replay burned |
| access token used as refresh → 401 | token class confusion (refresh side) |
| logout → old refresh → 401 | revocation works |
| logout-all → every session 401 | lost-device flow |
| reset-password → all refresh tokens dead | password change invalidates sessions |
| identical 401 for unknown email / wrong password | enumeration |
| expired/bogus tokens → 401 | signature + exp enforcement |

### Rate limiting — `test_rate_limiting.py`

```python
for _ in range(8): statuses.append((await client.post("/auth/login", data=...)).status_code)
first_ok = settings.auth_rate_limit_max - 1
assert all(s == 200 for s in statuses[:first_ok])
assert all(s == 429 for s in statuses[first_ok:])
assert "Retry-After" in r.headers
```

Plus the fail-open test (Redis mocked to raise → login still succeeds) and the
"failed attempts count too" test.

### Upload safety — `test_attachments.py`

```python
# disallowed type
assert (await client.post(..., json={"filename": "a.exe", "content_type": "application/x-msdownload", ...})).status_code == 422
# oversized
assert (... 999_999_999 ...).status_code == 422
# traversal sanitized
r = await client.post(..., json={"filename": "../../etc/passwd.txt", "content_type": "text/plain", "size": 12})
assert r.json()["attachment"]["filename"] == "passwd.txt"
# cross-tenant download
assert (await client.post(f"/api/v1/attachments/{aid}/download-url", headers=OH)).status_code == 404
```

### Idempotency abuse — `test_idempotency.py`

| Assertion | Pinned behavior |
| --- | --- |
| same key + same body → identical resource, `Idempotency-Replayed: true` | replay |
| same key + different body → 422 | key reuse conflict |
| same key, different user → both succeed | per-identity scoping |
| malformed key → 400 | format validation |
| no key → normal double-create | opt-in semantics |

### Realtime auth — `test_websockets.py`

```python
def test_socket_rejects_invalid_token(ws_client):
    with pytest.raises((WebSocketDisconnect, RuntimeError)):
        with ws_client.websocket_connect(f"/ws/projects/{project['id']}?token=garbage") as ws:
            ws.receive_json()

def test_socket_rejects_non_members(ws_client): ...   # outsider token → close
```

## What the suite does **not** cover (honest list)

| Gap | Why it matters |
| --- | --- |
| The `get_current_user` token-type gap (`auth/01`) | no test asserts refresh-token-as-access is rejected on HTTP |
| SSRF on webhook URLs | no test that internal addresses are blocked (they are not — `infrastructure/09`) |
| Content-type spoofing (declared vs actual bytes) | fake storage can't sniff; real gap documented |
| Cross-tenant cache poisoning | keys embed org id; no adversarial test |
| Rate-limit bypass via header spoofing | `X-Forwarded-For` ignored by design; untested |

These are exactly the items to write next, listed in `mastery/10`.

## Django/DRF comparison 🔵

TeamFlow has no equivalent of DRF's permission-class test matrix — its
"permissions" are service code, so security tests are indistinguishable from
behavioral tests. That is the point of the architecture: security *is* behavior.

## Review questions

1. Why do IDOR tests assert 404 rather than 403? What would 403 reveal?
2. Which single test proves refresh-token reuse burns the whole token family?
3. What does the traversal test prove about `sanitize_filename` even though
   storage is faked?
4. Pick one gap from the honest list above and write the test you'd add first.
