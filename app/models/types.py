"""Custom SQLAlchemy column types."""

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.crypto import decrypt_secret, encrypt_secret


class EncryptedString(TypeDecorator):
    """Transparently Fernet-encrypts a text column at the DB boundary, so
    services keep reading/writing plaintext while the database stores only
    ciphertext. Uses TEXT because ciphertext is longer than the plaintext."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        return encrypt_secret(value)

    def process_result_value(self, value, dialect):  # noqa: ANN001
        return decrypt_secret(value)
