"""Unit tests: pure business logic, no I/O."""

from datetime import timedelta

from app.core.security import decode_token, hash_password, verify_password
from app.services.integrations.email import render
from app.services.integrations.webhook_signing import sign_payload
from app.services.tasks import STATUS_TRANSITIONS


def test_password_hash_roundtrip():
    hashed = hash_password("supersecret123")
    assert hashed != "supersecret123"
    assert verify_password("supersecret123", hashed)
    assert not verify_password("wrong-password", hashed)


def test_password_hash_is_salted():
    assert hash_password("same") != hash_password("same")


def test_token_roundtrip_and_expiry():
    from app.core.security import create_token

    token = create_token("user-1", "access", timedelta(seconds=-1))
    import jwt

    try:
        decode_token(token)
        raise AssertionError("expired token should not decode")
    except jwt.ExpiredSignatureError:
        pass


def test_status_transitions_are_well_formed():
    assert set(STATUS_TRANSITIONS) == {"todo", "in_progress", "in_review", "done"}
    # every reachable target must itself be a defined state
    for source, targets in STATUS_TRANSITIONS.items():
        assert source in {"todo", "in_progress", "in_review", "done"}
        for target in targets:
            assert target in STATUS_TRANSITIONS, target


def test_todo_cannot_skip_to_done():
    assert "done" not in STATUS_TRANSITIONS["todo"]


def test_done_can_reopen():
    assert "in_progress" in STATUS_TRANSITIONS["done"]


def test_webhook_signature_is_verifiable():
    body = b'{"event": "task.created"}'
    ts = "1717000000"
    sig = sign_payload("shhh", ts, body)
    assert sig.startswith("v1=")
    # recompute the same way a receiver would
    import hashlib
    import hmac

    expected = hmac.new(b"shhh", f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    assert sig == "v1=" + expected
    assert sign_payload("shhh", ts, b"tampered") != sig


def test_email_templates_render():
    subject, body = render("password_reset", {"reset_link": "http://x/reset?token=abc"})
    assert "Reset your TeamFlow password" == subject
    assert "http://x/reset?token=abc" in body
    subject2, body2 = render("organization_invite", {"organization": "Acme", "role": "manager"})
    assert "Acme" in body2 and "manager" in body2
