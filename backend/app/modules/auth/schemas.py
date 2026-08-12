import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str
    role: str


# ── User management (admin only) ───────────────────────────────────────────

class UserDetailResponse(BaseModel):
    """UserResponse plus the fields the admin screen needs.

    Deliberately never includes password_hash.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str
    role: str
    is_active: bool
    created_at: datetime


class UserCreateRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    # 12 chars because this app holds credentials that can spend money on a
    # live advertising account.
    password: str = Field(min_length=12, max_length=128)
    role: Literal["admin", "user"] = "user"


class UserUpdateRequest(BaseModel):
    """All optional — the screen sends only what changed."""
    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None


class PasswordResetRequest(BaseModel):
    password: str = Field(min_length=12, max_length=128)
