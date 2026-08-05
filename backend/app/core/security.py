"""
Password hashing and JWT creation/validation.

No sessions table — tokens are stateless. There is no server-side revocation mechanism in
Sprint 1A; a user re-logs in once a token expires (JWT_EXPIRE_MINUTES, default 8 hours).
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def create_access_token(user_id: str, role: str, expires_minutes: int | None = None) -> dict[str, Any]:
    expire_minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    now = datetime.now(timezone.utc)
    expire_at = now + timedelta(minutes=expire_minutes)

    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": expire_at,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expire_minutes * 60,
    }


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError (or a subclass) on invalid/expired/tampered tokens."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
