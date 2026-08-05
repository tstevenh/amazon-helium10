"""
Pydantic schemas for the accounts module (Sprint 1B, updated Sprint 3.5).
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ── Enums ─────────────────────────────────────────────────────────────────

class ConnectionMode(str, Enum):
    """Whether the app is running against real Amazon Ads or mock data."""
    mock = "mock"
    real = "real"


# ── Request bodies ────────────────────────────────────────────────────────

class AccountCreate(BaseModel):
    name: str


# ── Embedded sub-schemas ──────────────────────────────────────────────────

class CredentialStatus(BaseModel):
    """
    Credential and connection health for a seller account.

    Fields
    ------
    connected       True if an OAuth credential row exists for this account.
    token_expires_at  UTC expiry of the stored access token; None if not set.
    mode            "mock" or "real" depending on AMAZON_MOCK_MODE.
    last_synced_at  UTC timestamp of the most recent profile sync; None if never synced.
    """
    connected: bool
    token_expires_at: Optional[datetime] = None
    mode: ConnectionMode = ConnectionMode.mock
    last_synced_at: Optional[datetime] = None


# ── Connection diagnostics ────────────────────────────────────────────────

class ConnectionTestStep(BaseModel):
    """
    Result of a single diagnostic step in a connection test.

    name   Short identifier: credentials_stored | token_decrypt |
                             token_refresh | profiles_api
    passed True if the step succeeded.
    detail Human-readable explanation of the result or error.
    """
    name: str
    passed: bool
    detail: str


class ConnectionTestResponse(BaseModel):
    """
    Full result of GET /accounts/{id}/connection-test.

    steps         Ordered list of diagnostic steps, each with passed/detail.
    profile_count Number of profiles returned by Amazon (0 if steps failed).
    error         First error message encountered; None if all steps passed.
    """
    account_id: uuid.UUID
    mode: ConnectionMode
    steps: list[ConnectionTestStep]
    profile_count: int
    error: Optional[str] = None


# ── Response schemas ──────────────────────────────────────────────────────

class AccountListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    profile_count: int
    credential_status: CredentialStatus


class AccountDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime
    credential_status: CredentialStatus


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seller_account_id: uuid.UUID
    amazon_profile_id: int
    marketplace_code: str
    country_code: Optional[str] = None
    currency_code: Optional[str] = None
    timezone: Optional[str] = None
    status: str
    last_synced_at: Optional[datetime] = None


class OAuthStartResponse(BaseModel):
    auth_url: str
    seller_account_id: uuid.UUID
    note: str = (
        "Visit auth_url to authorise Amazon Ads access. "
        "Amazon will redirect back to AMAZON_REDIRECT_URI with code and state."
    )


class OAuthCallbackResponse(BaseModel):
    message: str
    seller_account_id: uuid.UUID
    profiles_synced: int


class SyncResponse(BaseModel):
    message: str
    seller_account_id: uuid.UUID
    profiles_synced: int
