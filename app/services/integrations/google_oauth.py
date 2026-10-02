"""Google OAuth 2.0 / OpenID Connect integration (Sign in with Google).

Flow (authorization code + PKCE, frontend never sees the client secret):
  1. `/auth/google/start` builds the consent URL and stashes state+verifier.
  2. Google redirects back to `/auth/google/callback` with `code` + `state`.
  3. `exchange_code()` trades the code for tokens (server-to-server).
  4. `verify_id_token()` validates the OIDC ID token against Google's JWKS
     (RS256 signature, audience, issuer, expiry) and returns the identity.

Only this module talks to Google; the auth service deals in identities.
"""

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import settings
from app.core.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 (URL, not a secret)
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
GOOGLE_SCOPES = "openid email profile"


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    name: str


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorize_url(redirect_uri: str, state: str, challenge: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str, redirect_uri: str, code_verifier: str) -> str:
    """Trades the authorization code for tokens; returns the raw `id_token`."""
    payload = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.google_oauth_timeout_seconds,
            trust_env=settings.webhook_httpx_trust_env,
        ) as client:
            response = await client.post(GOOGLE_TOKEN_URL, data=payload)
    except httpx.HTTPError as exc:
        raise ExternalServiceError("Could not reach Google") from exc

    if response.status_code != 200:
        logger.warning(
            "Google token exchange failed (%s): %s", response.status_code, response.text[:500]
        )
        raise ExternalServiceError("Google rejected the sign-in attempt")

    id_token = response.json().get("id_token")
    if not id_token:
        raise ExternalServiceError("Google did not return an identity token")
    return id_token


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    # cache_keys + lifespan keep key fetches off the hot path.
    return jwt.PyJWKClient(
        GOOGLE_JWKS_URL, cache_keys=True, lifespan=3600, timeout=settings.google_oauth_timeout_seconds
    )


def verify_id_token(id_token: str) -> GoogleIdentity:
    """Blocking (JWKS fetch) — call via run_in_threadpool from async code."""
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(id_token)
        payload = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            # Signature/aud above; expiry + issuer are validated below so the
            # error surface stays uniform.
            options={"require": ["exp", "iat", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise ExternalServiceError("Google identity token is invalid") from exc

    if payload.get("iss") not in GOOGLE_ISSUERS:
        raise ExternalServiceError("Google identity token has a bad issuer")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ExternalServiceError("Google identity token has expired")

    return GoogleIdentity(
        sub=str(payload.get("sub", "")),
        email=str(payload.get("email", "")).lower(),
        email_verified=str(payload.get("email_verified", "")).lower() == "true",
        name=str(payload.get("name", "") or ""),
    )
