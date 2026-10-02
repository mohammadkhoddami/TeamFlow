"""Unit tests: Google OAuth URL/PKCE helpers (no network)."""

import base64
import hashlib

from app.core.config import settings
from app.services.integrations import google_oauth


def test_pkce_challenge_is_s256(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid")
    verifier = google_oauth.generate_code_verifier()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert google_oauth.code_challenge(verifier) == expected


def test_authorize_url_carries_security_params(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid")
    url = google_oauth.authorize_url("http://localhost/callback", "state-1", "challenge-1")
    assert url.startswith(google_oauth.GOOGLE_AUTHORIZE_URL)
    assert "client_id=cid" in url
    assert "state=state-1" in url
    assert "code_challenge=challenge-1" in url
    assert "code_challenge_method=S256" in url
    assert "scope=openid+email+profile" in url or "scope=openid%20email%20profile" in url


def test_generate_state_and_verifier_are_unique():
    assert google_oauth.generate_state() != google_oauth.generate_state()
    assert google_oauth.generate_code_verifier() != google_oauth.generate_code_verifier()
