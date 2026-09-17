# Testing 02 — Unit Testing

## Concept

Unit tests exercise pure logic with no I/O: no database, no Redis, no network.
They are fast, deterministic, and pin the behavior of the functions most likely
to be reused or subtly broken.

## What TeamFlow unit-tests — `tests/unit/test_security_helpers.py`

| Test | Pins |
| --- | --- |
| `test_password_hash_roundtrip` | hash != plaintext; verify succeeds; wrong password fails |
| `test_password_hash_is_salted` | same input → different hashes (per-hash salt) |
| `test_token_roundtrip_and_expiry` | expired tokens raise `ExpiredSignatureError` |
| `test_status_transitions_are_well_formed` | every state defined; targets reachable |
| `test_todo_cannot_skip_to_done` | the domain rule "no skipping" |
| `test_done_can_reopen` | reopening is allowed |
| `test_webhook_signature_is_verifiable` | HMAC matches an independent recomputation; tampered body differs |
| `test_email_templates_render` | templates produce subject + interpolated body |

Each of these is a **regression tripwire** for a rule that lives in production
code:

```python
def test_webhook_signature_is_verifiable():
    body = b'{"event": "task.created"}'
    ts = "1717000000"
    sig = sign_payload("shhh", ts, body)
    assert sig.startswith("v1=")
    import hashlib, hmac
    expected = hmac.new(b"shhh", f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    assert sig == "v1=" + expected
    assert sign_payload("shhh", ts, b"tampered") != sig
```

Note the style: reproduce the receiver's verification **independently** using
the stdlib, so the test doesn't just re-run the implementation. If
`sign_payload` changes its formula, receivers break — and this test fails.

## What makes something unit-testable in TeamFlow

The layer boundaries (`architecture/01-layered-architecture.md`) are what make
these tests possible:

- `app/core/security.py` — pure functions, no session, no request
- `app/services/integrations/webhook_signing.py` — pure HMAC
- `app/services/integrations/email.py` — pure template rendering
- `app/services/tasks.py::STATUS_TRANSITIONS` — a data structure

If business rules were embedded in route handlers (FastAPI's default drift),
none of this would be testable without HTTP.

## What TeamFlow does *not* unit-test (and why)

| Not unit-tested | Reason |
| --- | --- |
| Services (e.g. `update_task`) | they orchestrate DB + events; integration tests cover them against real infrastructure |
| Repositories | their contract is SQL behavior; unit-mocking a session proves nothing |
| Dependencies | covered through API tests |
| `sanitize_filename` | could be unit-tested (pure); currently covered indirectly by the attachment integration test — an honest gap (`mastery/10`) |

The bias: unit tests capture **pure invariants**; everything with I/O semantics
is tested where the semantics live.

## Running just the unit tests

```bash
uv run pytest tests/unit -q          # ~4s, no services required
```

They run with no PostgreSQL or Redis — a property worth preserving: if a unit
test starts needing infrastructure, it has stopped being a unit test.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `SimpleTestCase` (no DB) | plain pytest functions |
| `TestCase` (DB + rollback) | not the unit layer — integration tests use truncation |
| Model methods unit-tested | pure helpers in `core/`, `integrations/` |
| `mock.patch` heavy unit tests | avoided where possible; dependency overrides at integration level |

## Common mistakes

1. **Testing the mock, not the logic** — asserting a mocked session received
   `add()` proves little. TeamFlow pushes I/O down and tests the pure parts.
2. **Unit-testing business rules that need state** (transitions are pure — good;
   "cannot delete a project with tasks" needs DB — integration).
3. **Copy-pasting the implementation into the test** — the HMAC test recomputes
   independently on purpose; a duplicate implementation is not a check.
4. **Letting "unit" tests touch Postgres** — slow suite, flaky ordering, and
   they stop being runnable in a bare environment.

## Review questions

1. Why is `STATUS_TRANSITIONS` unit-testable while `update_task` is not?
2. What does the HMAC test protect that a round-trip test (`verify(sign(x))`)
   would not?
3. Which of these would you classify as unit vs integration: password hashing,
   idempotency replay, template rendering, invitation acceptance?
