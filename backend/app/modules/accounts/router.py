"""
Accounts router — Sprint 1B, updated Sprint 3.5.

Endpoints
---------
POST   /accounts                         Admin only — create seller account
GET    /accounts                         Admin+User — list accounts
GET    /accounts/oauth/callback          Public (Amazon redirect) — OAuth callback
GET    /accounts/{id}                    Admin+User — get account detail
GET    /accounts/{id}/profiles           Admin+User — list profiles for account
GET    /accounts/{id}/oauth/start        Admin only — get Amazon consent URL
GET    /accounts/{id}/oauth/callback     Admin+User — alias callback
POST   /accounts/{id}/profiles/sync      Admin only — manually re-sync profiles
GET    /accounts/{id}/connection-test    Admin+User — run 4-step diagnostics

OAuth callback note
-------------------
The canonical callback URL Amazon redirects to is the static path /accounts/oauth/callback
(no {id} in path). Register AMAZON_REDIRECT_URI=http://localhost:8000/accounts/oauth/callback
in your Amazon LWA app. The seller_account_id is carried in the signed JWT state parameter.

After processing, both callback endpoints redirect the browser to the frontend account
detail page instead of returning raw JSON. This gives users a proper success/error UI.
"""
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text as _sa_text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.modules.accounts.schemas import (
    AccountCreate,
    AccountDetail,
    AccountListItem,
    ConnectionTestResponse,
    OAuthStartResponse,
    ProfileResponse,
    SyncResponse,
)
from app.modules.accounts.service import AccountService
from app.modules.auth.models import User

router = APIRouter(prefix="/accounts", tags=["accounts"])


# ── Static routes (must be declared BEFORE /{id} to avoid path conflicts) ─


@router.get("/oauth/callback")
def oauth_callback(
    code: str = Query(..., description="Authorization code from Amazon"),
    state: str = Query(..., description="Signed JWT state from oauth/start"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """
    Amazon redirects here after the user grants consent.
    No Bearer token required — identity is validated via the signed state JWT.

    On success: redirects browser to {FRONTEND_URL}/accounts/{id}?connected=true
    On error:   redirects browser to {FRONTEND_URL}/accounts?oauth_error=<message>
    """
    try:
        svc = AccountService(db)
        result = svc.handle_oauth_callback(code=code, state=state)
        seller_account_id = result["seller_account_id"]
        redirect_url = f"{settings.frontend_url}/accounts/{seller_account_id}?connected=true"
    except Exception as exc:
        import urllib.parse
        error_msg = urllib.parse.quote(str(exc))
        redirect_url = f"{settings.frontend_url}/accounts?oauth_error={error_msg}"
    return RedirectResponse(url=redirect_url, status_code=302)


# ── Collection routes ─────────────────────────────────────────────────────


@router.post("", response_model=AccountDetail, status_code=201)
def create_account(
    payload: AccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> AccountDetail:
    """Admin only. Create a new seller account."""
    svc = AccountService(db)
    account = svc.create_account(payload.name, current_user)
    detail = svc.get_account_detail(account)
    return AccountDetail(**detail)


@router.get("", response_model=list[AccountListItem])
def list_accounts(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[AccountListItem]:
    """Admin and User. List all seller accounts with profile count and credential status."""
    svc = AccountService(db)
    return [AccountListItem(**item) for item in svc.list_accounts()]


# ── Item routes ───────────────────────────────────────────────────────────


@router.get("/{account_id}/connection-test", response_model=ConnectionTestResponse)
def connection_test(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ConnectionTestResponse:
    """
    Admin and User. Run a 4-step diagnostic to verify the Amazon Ads connection.

    Steps:
      1. credentials_stored — credential row exists in DB
      2. token_decrypt      — FERNET_KEY can decrypt the stored refresh token
      3. token_refresh      — Amazon LWA accepts the refresh token and issues a new access token
      4. profiles_api       — Amazon Ads /v2/profiles returns at least one profile

    In mock mode, steps 3 and 4 are simulated (no real HTTP calls).
    All errors are captured into step.detail — never returns a generic 500.
    Secrets are never included in the response.
    """
    svc = AccountService(db)
    account = svc.get_account_or_404(account_id)
    return svc.connection_test(account)


@router.get("/{account_id}", response_model=AccountDetail)
def get_account(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AccountDetail:
    """Admin and User. Get a single seller account with credential status."""
    svc = AccountService(db)
    account = svc.get_account_or_404(account_id)
    detail = svc.get_account_detail(account)
    return AccountDetail(**detail)


@router.get("/{account_id}/profiles", response_model=list[ProfileResponse])
def list_profiles(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ProfileResponse]:
    """Admin and User. Return all stored profiles for this account."""
    svc = AccountService(db)
    account = svc.get_account_or_404(account_id)
    profiles = svc.profile_repo.get_by_account(account.id)
    return [ProfileResponse.model_validate(p) for p in profiles]


@router.get("/{account_id}/oauth/start", response_model=OAuthStartResponse)
def oauth_start(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> OAuthStartResponse:
    """
    Admin only. Returns the Amazon Ads OAuth consent URL.
    Open auth_url in a browser to begin the OAuth flow.
    Amazon will redirect to AMAZON_REDIRECT_URI (/accounts/oauth/callback) when done.
    """
    svc = AccountService(db)
    account = svc.get_account_or_404(account_id)
    auth_url = svc.build_oauth_start_url(account, current_user)
    return OAuthStartResponse(auth_url=auth_url, seller_account_id=account_id)


@router.get("/{account_id}/oauth/callback")
def oauth_callback_with_id(
    account_id: uuid.UUID,
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """
    Alias of /accounts/oauth/callback. Also validates that path account_id
    matches the seller_account_id in the state JWT.

    Redirects browser to frontend on success or error (same as the static callback).
    """
    import jwt as pyjwt
    from fastapi import HTTPException, status as http_status

    try:
        decoded = pyjwt.decode(state, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        state_account_id = decoded.get("seller_account_id")
    except pyjwt.PyJWTError:
        state_account_id = None

    if state_account_id and str(account_id) != state_account_id:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Path account_id does not match state token seller_account_id",
        )

    try:
        svc = AccountService(db)
        result = svc.handle_oauth_callback(code=code, state=state)
        seller_account_id = result["seller_account_id"]
        redirect_url = f"{settings.frontend_url}/accounts/{seller_account_id}?connected=true"
    except Exception as exc:
        import urllib.parse
        error_msg = urllib.parse.quote(str(exc))
        redirect_url = f"{settings.frontend_url}/accounts?oauth_error={error_msg}"
    return RedirectResponse(url=redirect_url, status_code=302)


@router.post("/{account_id}/profiles/sync", response_model=SyncResponse)
def sync_profiles(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> SyncResponse:
    """Admin only. Re-sync Amazon Ads profiles for this account from the API."""
    svc = AccountService(db)
    account = svc.get_account_or_404(account_id)
    profiles = svc.sync_profiles(account)
    return SyncResponse(
        message="Profile sync complete",
        seller_account_id=account_id,
        profiles_synced=len(profiles),
    )


@router.delete("/{account_id}", status_code=204)
def delete_account(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    """
    Admin only. Hard-delete a seller account, its OAuth credential, and all profiles.
    This action is irreversible.
    """
    svc = AccountService(db)
    account = svc.get_account_or_404(account_id)
    svc.delete_account(account)


@router.get("/{account_id}/profile-counts")
def profile_counts(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> JSONResponse:
    """Row counts per marketplace, so the UI can say WHERE the data is.

    An operator whose saved selection lands on an empty marketplace should be
    told which one has data — not told to run an hour-long sync that will
    change nothing. Two people have now lost time to that wrong advice.

    One grouped query, not one per profile.
    """
    rows = db.execute(_sa_text("""
        SELECT p.id, p.country_code,
               count(DISTINCT c.id) FILTER (WHERE c.deleted_at IS NULL) AS campaigns
        FROM ads_profiles p
        LEFT JOIN campaigns c ON c.profile_id = p.id
        WHERE p.seller_account_id = :aid
        GROUP BY p.id, p.country_code
        ORDER BY 3 DESC
    """), {"aid": str(account_id)}).fetchall()

    return JSONResponse(content=[
        {
            "profile_id": str(r[0]),
            "country_code": r[1],
            "campaigns": int(r[2] or 0),
        }
        for r in rows
    ])
