"""
Symmetric field-level encryption for sensitive DB columns.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` package.
The key is loaded once from the FIELD_ENCRYPTION_KEY environment variable.

Encrypted values are stored with an "enc:" prefix so legacy plaintext rows
can be read transparently during and after migration.

Usage via SQLAlchemy TypeDecorator (see models.py EncryptedString):
    All reads and writes go through process_result_value / process_bind_param,
    so the rest of the codebase never needs to call encrypt/decrypt directly.
"""

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

_ENC_PREFIX = "enc:"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.getenv("FIELD_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "FIELD_ENCRYPTION_KEY is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
            "and add it to your .env file."
        )
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    """Return prefixed ciphertext. No-ops if already encrypted."""
    if plaintext is None:
        return None
    if plaintext.startswith(_ENC_PREFIX):
        return plaintext  # idempotent
    token = _fernet().encrypt(plaintext.encode()).decode()
    return f"{_ENC_PREFIX}{token}"


def decrypt(value: str) -> str:
    """
    Decrypt an encrypted value.
    Transparently returns legacy plaintext values unchanged so rows written
    before encryption was introduced continue to work until re-saved.
    """
    if value is None:
        return None
    if not value.startswith(_ENC_PREFIX):
        return value  # legacy plaintext — safe to return as-is
    try:
        return _fernet().decrypt(value[len(_ENC_PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Failed to decrypt field value — wrong FIELD_ENCRYPTION_KEY or corrupted data."
        ) from exc


def is_encrypted(value: str) -> bool:
    return bool(value and value.startswith(_ENC_PREFIX))
