"""
Fernet symmetric encryption helpers for storing Amazon OAuth tokens at rest.

Usage:
    from app.core.encryption import encrypt, decrypt

    stored = encrypt("my_refresh_token")  # store this in DB
    plain  = decrypt(stored)              # retrieve and decrypt when needed

The FERNET_KEY must be a valid URL-safe base64-encoded 32-byte key.
Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    key = settings.fernet_key
    if not key:
        raise RuntimeError(
            "FERNET_KEY is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string and return a URL-safe base64 token."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token back to plaintext. Raises InvalidToken if tampered."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Token decryption failed — token may be corrupted or key mismatch") from exc
