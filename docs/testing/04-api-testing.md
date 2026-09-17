# Testing 04 — API Testing

## Concept

API tests assert the HTTP contract: status codes, response shapes, error
formats, and pagination envelopes. In TeamFlow these are the bulk of the suite,
written with `httpx.AsyncClient` over `ASGITransport` (`testing/03`).

## What "API test" checks that integration tests also check (and vice versa)

| Concern | Belongs to |
| --- | --- |
| Status codes, envelope shapes, field names | API test |
| Business rules (transitions, ranks) | both — API tests assert the rule *through* HTTP |
| SQL correctness | integration (the API response reveals it) |
| Error body format (`{"detail": ...}`) | API test |
| OpenAPI/validation (422 shapes) | API test |

In practice TeamFlow's `tests/integration/*` files are API tests — the split is
conceptual: *what contract does this assertion pin?*

## The recurring assertions

### Status-code semantics

```python
r = await client.post("/api/v1/auth/register", json={...})
assert r.status_code == 201                    # created

r = await client.delete(f"/api/v1/tasks/{task['id']}", headers=H)
assert r.status_code == 204                    # no content

r = await client.post("/api/v1/tasks/{id}/move", json={"status": "done"}, headers=H)
assert r.status_code == 422                    # business rule

r = await client.post(f"/api/v1/organizations/{slug}/invitations", ..., headers=H)
assert r.status_code == 409                    # conflict
```

### Response-shape pinning

```python
user = r.json()
assert "hashed_password" not in user and "password" not in user       # response_model
assert user["email"] == EMAIL
```

### The page envelope

```python
body = r.json()
assert body["total"] == 2 and body["limit"] == 2 and body["offset"] == 1
assert [t["title"] for t in body["items"]] == ["Beta refactoring", "Delta archived"]
```

`total` proves the count query matches the filters; `items` proves ordering and
windowing.

### Error-body format

```python
assert "Incorrect email or password" in r.json()["detail"]     # 401 shape
assert r1.json() == r2.json()                                   # forgot-password: no enumeration
```

### Validation

```python
r = await client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": PASSWORD})
assert r.status_code == 422                    # Pydantic
r = await client.post("/api/v1/organizations", json={"name": "X", "slug": "Invalid_Slug!"}, headers=H)
assert r.status_code == 422                    # pattern
```

## Testing headers and idempotency end-to-end

```python
r1 = await client.post("/api/v1/organizations/idem-org/projects", json=body,
                       headers={**H, "Idempotency-Key": KEY})
r2 = await client.post(..., headers={**H, "Idempotency-Key": KEY})
assert r1.json()["id"] == r2.json()["id"]
assert r2.headers.get("idempotency-replayed") == "true"        # middleware header
r = await client.get("/api/v1/organizations/idem-org/projects", headers=H)
assert len(r.json()) == 1                                       # only one row created
```

This is a full-stack test: middleware body buffering, claim row, response
capture, replay — verified through the public interface.

## Auth in tests

`auth_headers(user)` builds `{"Authorization": f"Bearer {user['token']}"}`.
Every authenticated call goes through the real dependency chain (JWT decode,
user load, `is_active`). Negative tests remove or corrupt the header:

```python
r = await client.get("/api/v1/auth/me")
assert r.status_code == 401
r = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
assert r.status_code == 401
```

## Django/DRF comparison 🔵

| DRF | TeamFlow |
| --- | --- |
| `self.client.get("/tasks/", format="json")` | `await client.get("/api/v1/tasks/{id}", headers=H)` |
| `response.data` | `response.json()` |
| `reverse("task-detail", args=[id])` | literal paths (builders hold ids) |
| `APITestCase` mixins | plain pytest fixtures |
| 400 for validation | **422** — assertions must expect FastAPI semantics |

The 400-vs-422 difference is the most common porting bug when Django devs write
assertions from muscle memory.

## Common mistakes

1. **Asserting only `status_code`** — a 200 with the wrong body still passes.
   Pin at least one field from the response.
2. **Reusing tokens across tests** — truncation deletes the user; the
   dependency then 401s. Create users per test (`make_user`).
3. **Forgetting headers on one call in a chain** and debugging a 401 that is
   actually a test bug.
4. **Hardcoding ids** — always take ids from the creation response.
5. **Expecting 400 for validation** (DRF habit) — TeamFlow returns 422 with a
   normalized detail list.

## Review questions

1. What does `total` in the page envelope prove that `len(items)` doesn't?
2. Which headers do TeamFlow's tests read from responses, and what do they
   prove?
3. Why does the forgot-password test assert *identical* responses for known and
   unknown emails?
4. Write from memory the assertions pinning: wrong login → 401, missing token →
   401, illegal transition → 422.
