"""MFA service: TOTP enrollment and verification (M4 enterprise security).

Stdlib-only RFC 6238 implementation (HMAC-SHA1, 30-second steps, 6 digits,
±1 step window) so no new dependency is introduced. Recovery codes are
single-use: only sha256 hashes are stored and a successful match rewrites the
list. Enrollment is two-phase — `setup_mfa` stores a disabled credential and
only `enable_mfa` (after a valid code) activates it, so an abandoned setup
never locks anyone out.

The login challenge token lives in Redis (`teamflow:mfa:{token}` -> user id,
300s TTL) and is consumed with GETDEL, so an intercepted challenge cannot be
replayed after a successful verification.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
import uuid
from urllib.parse import quote, urlencode

from redis.asyncio import Redis
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.models import MfaCredential, User, utcnow

TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6
TOTP_WINDOW_STEPS = 1
RECOVERY_CODE_COUNT = 10
MFA_LOGIN_TTL_SECONDS = 300
MFA_LOGIN_PREFIX = "teamflow:mfa"
_RECOVERY_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def generate_secret() -> str:
    """20 random bytes, base32-encoded (160 bits, RFC 4226 recommendation)."""
    return base64.b32encode(secrets.token_bytes(20)).decode()


def _decode_secret(secret: str) -> bytes:
    normalized = secret.strip().upper().replace(" ", "")
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    return base64.b32decode(normalized + padding)


def _code_for_counter(secret: str, counter: int) -> str:
    digest = hmac.new(
        _decode_secret(secret), struct.pack(">Q", counter), hashlib.sha1
    ).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % (10**TOTP_DIGITS):0{TOTP_DIGITS}d}"


def totp_now(secret: str, at_time: float | None = None) -> str:
    timestamp = time.time() if at_time is None else at_time
    return _code_for_counter(secret, int(timestamp) // TOTP_STEP_SECONDS)


def verify_totp(secret: str, code: str, at_time: float | None = None) -> bool:
    """±1 step window tolerates clock drift without widening the brute-force
    surface beyond 3 attempts per 30 seconds."""
    candidate = (code or "").strip().replace(" ", "")
    if len(candidate) != TOTP_DIGITS or not candidate.isdigit():
        return False
    timestamp = time.time() if at_time is None else at_time
    counter = int(timestamp) // TOTP_STEP_SECONDS
    for offset in range(-TOTP_WINDOW_STEPS, TOTP_WINDOW_STEPS + 1):
        if hmac.compare_digest(_code_for_counter(secret, counter + offset), candidate):
            return True
    return False


def otpauth_uri(secret: str, account: str, issuer: str = "TeamFlow") -> str:
    label = quote(f"{issuer}:{account}")
    params = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": TOTP_DIGITS,
            "period": TOTP_STEP_SECONDS,
        }
    )
    return f"otpauth://totp/{label}?{params}"


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def generate_recovery_codes(
    count: int = RECOVERY_CODE_COUNT,
) -> tuple[list[str], list[str]]:
    plain: list[str] = []
    while len(plain) < count:
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(8))
        candidate = f"{raw[:4]}-{raw[4:]}"
        if candidate not in plain:
            plain.append(candidate)
    return plain, [hash_recovery_code(code) for code in plain]


def _consume_recovery_code(credential: MfaCredential, code: str) -> bool:
    digest = hash_recovery_code(code)
    stored = credential.recovery_codes or []
    if digest not in stored:
        return False
    credential.recovery_codes = [item for item in stored if item != digest]
    return True


async def get_credential(db: AsyncSession, user_id: uuid.UUID) -> MfaCredential | None:
    statement = select(MfaCredential).where(MfaCredential.user_id == user_id)
    return (await db.execute(statement)).scalar_one_or_none()


async def enabled(db: AsyncSession, user_id: uuid.UUID) -> bool:
    credential = await get_credential(db, user_id)
    return bool(credential and credential.is_enabled)


async def setup_mfa(db: AsyncSession, user: User) -> tuple[str, str, list[str]]:
    """Starts (or restarts a pending) enrollment. Returns the shared secret,
    the provisioning URI, and freshly generated plain recovery codes. The
    credential stays disabled until `enable_mfa` proves possession."""
    credential = await get_credential(db, user.id)
    if credential and credential.is_enabled:
        raise ConflictError("MFA is already enabled")
    secret = generate_secret()
    plain_codes, hashed_codes = generate_recovery_codes()
    if credential is None:
        credential = MfaCredential(user_id=user.id, secret=secret)
    credential.secret = secret
    credential.is_enabled = False
    credential.recovery_codes = hashed_codes
    credential.confirmed_at = None
    credential.last_used_at = None
    db.add(credential)
    await db.flush()
    return secret, otpauth_uri(secret, user.email), plain_codes


async def enable_mfa(db: AsyncSession, user: User, code: str) -> None:
    credential = await get_credential(db, user.id)
    if credential is None:
        raise NotFoundError("MFA setup has not been started")
    if credential.is_enabled:
        raise ConflictError("MFA is already enabled")
    if not verify_totp(credential.secret, code):
        raise UnauthorizedError("Invalid authentication code")
    credential.is_enabled = True
    credential.confirmed_at = utcnow()
    db.add(credential)
    await db.flush()


async def disable_mfa(db: AsyncSession, user: User, code: str) -> None:
    credential = await get_credential(db, user.id)
    if credential is None or not credential.is_enabled:
        raise NotFoundError("MFA is not enabled")
    if not verify_totp(credential.secret, code) and not _consume_recovery_code(
        credential, code
    ):
        raise UnauthorizedError("Invalid authentication code")
    await db.delete(credential)
    await db.flush()


async def verify_login_code(db: AsyncSession, user: User, code: str) -> bool:
    """TOTP or single-use recovery code; recovery codes are consumed here.
    Changes flush into the caller's transaction (the session commit that
    issues the tokens persists `last_used_at` too)."""
    credential = await get_credential(db, user.id)
    if credential is None or not credential.is_enabled:
        return False
    if not verify_totp(credential.secret, code) and not _consume_recovery_code(
        credential, code
    ):
        return False
    credential.last_used_at = utcnow()
    db.add(credential)
    await db.flush()
    return True


# ------------------------------------------------- Redis login challenge


def login_token_key(token: str) -> str:
    return f"{MFA_LOGIN_PREFIX}:{token}"


async def store_login_token(redis: Redis, user_id: str) -> str:
    """Creates the one-time challenge token returned by /auth/login."""
    token = secrets.token_urlsafe(32)
    await redis.set(login_token_key(token), user_id, ex=MFA_LOGIN_TTL_SECONDS)
    return token


async def consume_login_token(redis: Redis, token: str) -> str | None:
    return await redis.getdel(login_token_key(token))
