"""Symmetric encryption for secrets that must be recovered later.

TOTP seeds, OIDC client secrets and webhook signing secrets are encrypted at
rest with Fernet (AES-128-CBC + HMAC). The key comes from
``SECRETS_ENCRYPTION_KEY`` (a urlsafe base64 32-byte Fernet key); when unset a
key is derived from the JWT ``secret_key`` so local/dev installs keep working.

Losing or rotating the key makes existing ciphertext unrecoverable - affected
credentials must be re-entered. ``decrypt_secret`` tolerates legacy plaintext
rows (values that are not Fernet tokens) so a partially migrated database
keeps functioning.
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)

_FERNET_PREFIX = "gAAAA"
_fallback_warned = False


def _fernet() -> Fernet:
    global _fallback_warned
    key = settings.secrets_encryption_key
    if not key:
        if not _fallback_warned:
            logger.warning(
                "SECRETS_ENCRYPTION_KEY is not set; deriving a key from "
                "secret_key. Set a dedicated key in production."
            )
            _fallback_warned = True
        digest = hashlib.sha256(
            f"teamflow-secrets:{settings.secret_key}".encode()
        ).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode())


def encrypt_secret(plain: str | None) -> str | None:
    if plain is None or plain == "":
        return plain
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if not value.startswith(_FERNET_PREFIX):
        # Legacy plaintext row written before encryption existed.
        return value
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError(
            "Stored secret cannot be decrypted: SECRETS_ENCRYPTION_KEY changed?"
        ) from exc
