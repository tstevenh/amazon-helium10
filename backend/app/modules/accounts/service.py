"""
Business logic for accounts, Amazon OAuth, and profile sync (Sprint 1B, updated Sprint 3.5).

Design notes
------------
* OAuth state is a short-lived JWT (10 min TTL) signed with JWT_SECRET_KEY.
  It carries seller_account_id and the id of the admin who initiated the flow
  so the callback can create the credential row with the correct created_by.

* The callback endpoint (/accounts/oauth/callback) is the static URI registered
  with Amazon. It has no Bearer-token auth — identity comes from the state JWT.
  An alias endpoint GET /accounts/{id}/oauth/callback is also exposed for callers
  who prefer to embed the account id in the path; it validates path id == state id.

* Token refresh is lazy: get_valid_access_token() checks token_expires_at against
  utcnow and refreshes only when needed. A 60-second buffer is used to avoid
  using a token that expires in transit.

* All Amazon API calls catch AmazonApiError specifically and re-raise as readable
  HTTPExceptions (502) rather than generic 500s.

* connection_test() runs a 4-step diagnostic: credentials_stored, token_decrypt,
  token_refresh, profiles_api. In mock mode, steps 3 and 4 are simulated.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone as tz
from typing import Optional

import jwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.core.amazon_ads import (
    AmazonApiError,
    build_auth_url,
    exchange_code_for_tokens,
    list_profiles,
    refresh_access_token,
)
from app.core.encryption import decrypt, encrypt
from app.modules.accounts.models import AdsProfile, SellerAccount
from app.modules.accounts.repository import (
    AdsProfileRepository,
    CredentialRepository,
    SellerAccountRepository,
)
from app.modules.accounts.schemas import (
    ConnectionMode,
    ConnectionTestResponse,
    ConnectionTestStep,
)
from app.modules.auth.models import User

logger = logging.getLogger(__name__)

# How long before a token expires we proactively refresh it.
_REFRESH_BUFFER_SECONDS = 60
# TTL for the OAuth state JWT (Amazon has up to 10 min to redirect back).
_STATE_TTL_MINUTES = 10


def _current_mode() -> ConnectionMode:
    return ConnectionMode.mock if settings.amazon_mock_mode else ConnectionMode.real


class AccountService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.account_repo = SellerAccountRepository(db)
        self.cred_repo = CredentialRepository(db)
        self.profile_repo = AdsProfileRepository(db)

    # ── Account CRUD ──────────────────────────────────────────────────────

    def create_account(self, name: str, current_user: User) -> SellerAccount:
        return self.account_repo.create(name=name, created_by=current_user.id)

    def get_account_or_404(self, account_id: uuid.UUID) -> SellerAccount:
        account = self.account_repo.get_by_id(account_id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Seller account {account_id} not found",
            )
        return account

    def list_accounts(self) -> list[dict]:
        """Return accounts augmented with profile_count and credential_status."""
        accounts = self.account_repo.list_all()
        mode = _current_mode()
        result = []
        for account in accounts:
            cred = self.cred_repo.get_by_account(account.id)
            profiles = self.profile_repo.get_by_account(account.id)
            # Most recent sync across all profiles for this account
            last_synced_at = max(
                (p.last_synced_at for p in profiles if p.last_synced_at),
                default=None,
            )
            result.append(
                {
                    "id": account.id,
                    "name": account.name,
                    "created_at": account.created_at,
                    "profile_count": len(profiles),
                    "credential_status": {
                        "connected": cred is not None,
                        "token_expires_at": cred.token_expires_at if cred else None,
                        "mode": mode,
                        "last_synced_at": last_synced_at,
                    },
                }
            )
        return result

    def get_account_detail(self, account: SellerAccount) -> dict:
        cred = self.cred_repo.get_by_account(account.id)
        profiles = self.profile_repo.get_by_account(account.id)
        last_synced_at = max(
            (p.last_synced_at for p in profiles if p.last_synced_at),
            default=None,
        )
        return {
            "id": account.id,
            "name": account.name,
            "created_at": account.created_at,
            "updated_at": account.updated_at,
            "credential_status": {
                "connected": cred is not None,
                "token_expires_at": cred.token_expires_at if cred else None,
                "mode": _current_mode(),
                "last_synced_at": last_synced_at,
            },
        }

    # ── OAuth flow ────────────────────────────────────────────────────────

    def build_oauth_start_url(self, account: SellerAccount, current_user: User) -> str:
        """
        Build the Amazon consent URL for this account.

        The state JWT encodes:
          - seller_account_id: which account is being connected
          - initiated_by:      who started the flow (used as created_by on callback)
          - exp:               10-minute TTL to prevent replay
        """
        now = datetime.now(tz.utc)
        state_payload = {
            "seller_account_id": str(account.id),
            "initiated_by": str(current_user.id),
            "exp": now + timedelta(minutes=_STATE_TTL_MINUTES),
            "iat": now,
        }
        state = jwt.encode(
            state_payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        return build_auth_url(state)

    def handle_oauth_callback(self, code: str, state: str) -> dict:
        """
        Handle the Amazon redirect-back after user grants consent.

        Steps:
        1. Decode & validate state JWT.
        2. Exchange authorization code for tokens.
        3. Encrypt tokens and upsert credentials row.
        4. Run profile sync immediately.
        5. Return summary.
        """
        # 1. Validate state
        try:
            decoded = jwt.decode(
                state,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth state token has expired. Start the OAuth flow again.",
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid OAuth state: {exc}",
            )

        seller_account_id = uuid.UUID(decoded["seller_account_id"])
        initiated_by = uuid.UUID(decoded["initiated_by"])

        account = self.get_account_or_404(seller_account_id)

        # 2. Exchange code for tokens
        try:
            token_data = exchange_code_for_tokens(code)
        except AmazonApiError as exc:
            logger.error("Token exchange failed for account %s: %s", seller_account_id, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Amazon token exchange failed: {exc}",
            )
        except Exception as exc:
            logger.error("Token exchange failed for account %s: %s", seller_account_id, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Amazon token exchange failed: {exc}",
            )

        # 3. Encrypt and store
        refresh_token = token_data["refresh_token"]
        access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3600)
        token_expires_at = datetime.now(tz.utc) + timedelta(seconds=expires_in)

        self.cred_repo.upsert(
            seller_account_id=seller_account_id,
            refresh_token_encrypted=encrypt(refresh_token),
            access_token_encrypted=encrypt(access_token),
            token_expires_at=token_expires_at,
            created_by=initiated_by,
        )

        # 4. Sync profiles
        profiles = self._do_sync_profiles(account, access_token)

        return {
            "message": "OAuth complete and profiles synced",
            "seller_account_id": seller_account_id,
            "profiles_synced": len(profiles),
        }

    # ── Token management ─────────────────────────────────────────────────

    def get_valid_access_token(self, account: SellerAccount, force_refresh: bool = False) -> str:
        """
        Return a valid (non-expired) decrypted access token.

        Lazily refreshes via refresh_token when within REFRESH_BUFFER_SECONDS of expiry.
        Raises 400 if the account has no credentials stored.
        Raises 502 with readable Amazon error message if refresh fails.
        """
        cred = self.cred_repo.get_by_account(account.id)
        if cred is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Account {account.id} has no stored credentials. "
                    "Complete the OAuth flow first."
                ),
            )

        now = datetime.now(tz.utc)
        needs_refresh = (
            force_refresh
            or cred.access_token_encrypted is None
            or cred.token_expires_at is None
            or (cred.token_expires_at - now).total_seconds() < _REFRESH_BUFFER_SECONDS
        )

        if needs_refresh:
            logger.warning("[token] Force-refreshing access token for account %s (force_refresh=%s)", account.id, force_refresh)
            try:
                plain_refresh = decrypt(cred.refresh_token_encrypted)
                token_data = refresh_access_token(plain_refresh)
            except AmazonApiError as exc:
                logger.error("Token refresh failed for account %s: %s", account.id, exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Amazon token refresh failed: {exc}",
                )
            except Exception as exc:
                logger.error("Token refresh failed for account %s: %s", account.id, exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Amazon token refresh failed: {exc}",
                )

            new_access = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            new_expires_at = datetime.now(tz.utc) + timedelta(seconds=expires_in)

            cred = self.cred_repo.update_access_token(
                cred,
                access_token_encrypted=encrypt(new_access),
                token_expires_at=new_expires_at,
            )
            logger.warning("[token] New token stored for account %s, expires_at=%s",
                           account.id, new_expires_at)
            return new_access

        return decrypt(cred.access_token_encrypted)

    # ── Profile sync ──────────────────────────────────────────────────────

    def sync_profiles(self, account: SellerAccount) -> list[AdsProfile]:
        """Fetch a fresh access token and run profile sync. Callable from any endpoint."""
        access_token = self.get_valid_access_token(account)
        return self._do_sync_profiles(account, access_token)

    def _do_sync_profiles(
        self, account: SellerAccount, access_token: str
    ) -> list[AdsProfile]:
        """
        Internal: call Amazon Profiles API and UPSERT results.

        Separated from sync_profiles() so the OAuth callback can pass the freshly
        exchanged access token directly without a redundant DB round-trip.
        """
        try:
            raw_profiles = list_profiles(access_token)
        except AmazonApiError as exc:
            logger.error("Profile sync failed for account %s: %s", account.id, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Amazon profile sync failed: {exc}",
            )
        except Exception as exc:
            logger.error("Profile sync failed for account %s: %s", account.id, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Amazon profile sync failed: {exc}",
            )

        # Duplicate check — reject if any profile is already owned by another account
        incoming_ids = [
            int(r["profileId"])
            for r in raw_profiles
            if r.get("profileId") is not None
        ]
        dup = self.profile_repo.find_duplicate_owner(incoming_ids, account.id)
        if dup:
            dup_profile_id, dup_account_name = dup
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Amazon profile {dup_profile_id} is already connected to "
                    f"another seller account: \"{dup_account_name}\". "
                    "Each Amazon Ads account can only be linked to one seller account."
                ),
            )

        synced: list[AdsProfile] = []
        for raw in raw_profiles:
            profile_id = raw.get("profileId")
            if profile_id is None:
                logger.warning("Profile missing profileId, skipping: %s", raw)
                continue

            account_info = raw.get("accountInfo", {})
            marketplace_code = account_info.get("marketplaceStringId", "")
            country_code = raw.get("countryCode")
            currency_code = raw.get("currencyCode")
            timezone_str = raw.get("timezone")

            profile = self.profile_repo.upsert(
                seller_account_id=account.id,
                amazon_profile_id=int(profile_id),
                marketplace_code=marketplace_code,
                country_code=country_code,
                currency_code=currency_code,
                timezone_str=timezone_str,
            )
            synced.append(profile)

        logger.info(
            "Synced %d profiles for account %s (mock=%s)",
            len(synced),
            account.id,
            settings.amazon_mock_mode,
        )
        return synced

    # ── Connection diagnostics ────────────────────────────────────────────

    def connection_test(self, account: SellerAccount) -> ConnectionTestResponse:
        """
        Run a 4-step diagnostic to verify the Amazon Ads connection.

        Steps (in order):
          1. credentials_stored  — check credential row exists in DB
          2. token_decrypt       — decrypt refresh token with FERNET_KEY
          3. token_refresh       — call Amazon LWA to get a fresh access token
          4. profiles_api        — call /v2/profiles and count returned profiles

        In mock mode, steps 3 and 4 are simulated (no real HTTP calls).

        Returns ConnectionTestResponse with per-step results and safe error messages.
        Never raises — all errors are captured into step detail.
        """
        mode = _current_mode()
        steps: list[ConnectionTestStep] = []
        profile_count = 0

        # Step 1: Credentials stored
        cred = self.cred_repo.get_by_account(account.id)
        if cred is not None:
            steps.append(ConnectionTestStep(
                name="credentials_stored",
                passed=True,
                detail="Credential row found in database",
            ))
        else:
            steps.append(ConnectionTestStep(
                name="credentials_stored",
                passed=False,
                detail="No credentials stored — complete the OAuth flow first",
            ))
            return ConnectionTestResponse(
                account_id=account.id,
                mode=mode,
                steps=steps,
                profile_count=0,
                error="No credentials stored",
            )

        # Step 2: Token decrypt
        plain_refresh: Optional[str] = None
        try:
            plain_refresh = decrypt(cred.refresh_token_encrypted)
            if plain_refresh:
                steps.append(ConnectionTestStep(
                    name="token_decrypt",
                    passed=True,
                    detail="Refresh token decrypted successfully",
                ))
            else:
                steps.append(ConnectionTestStep(
                    name="token_decrypt",
                    passed=False,
                    detail="Decrypted refresh token is empty — re-run OAuth flow",
                ))
                return ConnectionTestResponse(
                    account_id=account.id,
                    mode=mode,
                    steps=steps,
                    profile_count=0,
                    error="Refresh token empty after decrypt",
                )
        except Exception as exc:
            err = f"Fernet decrypt failed: {exc}. Check that FERNET_KEY matches the key used when credentials were stored."
            steps.append(ConnectionTestStep(
                name="token_decrypt",
                passed=False,
                detail=err,
            ))
            return ConnectionTestResponse(
                account_id=account.id,
                mode=mode,
                steps=steps,
                profile_count=0,
                error=err,
            )

        # Mock mode: simulate remaining steps
        if settings.amazon_mock_mode:
            steps.append(ConnectionTestStep(
                name="token_refresh",
                passed=True,
                detail="Mock mode — skipped real Amazon LWA call",
            ))
            steps.append(ConnectionTestStep(
                name="profiles_api",
                passed=True,
                detail="Mock mode — using mock profiles (2 profiles)",
            ))
            return ConnectionTestResponse(
                account_id=account.id,
                mode=mode,
                steps=steps,
                profile_count=2,
                error=None,
            )

        # Step 3: Token refresh (real mode only)
        access_token: Optional[str] = None
        try:
            token_data = refresh_access_token(plain_refresh)
            access_token = token_data["access_token"]
            steps.append(ConnectionTestStep(
                name="token_refresh",
                passed=True,
                detail="Access token refreshed successfully via Amazon LWA",
            ))
        except AmazonApiError as exc:
            steps.append(ConnectionTestStep(
                name="token_refresh",
                passed=False,
                detail=str(exc),
            ))
            return ConnectionTestResponse(
                account_id=account.id,
                mode=mode,
                steps=steps,
                profile_count=0,
                error=str(exc),
            )
        except Exception as exc:
            err = f"Token refresh failed: {exc}"
            steps.append(ConnectionTestStep(
                name="token_refresh",
                passed=False,
                detail=err,
            ))
            return ConnectionTestResponse(
                account_id=account.id,
                mode=mode,
                steps=steps,
                profile_count=0,
                error=err,
            )

        # Step 4: Profiles API (real mode only)
        try:
            raw_profiles = list_profiles(access_token)
            profile_count = len(raw_profiles)
            steps.append(ConnectionTestStep(
                name="profiles_api",
                passed=True,
                detail=f"Retrieved {profile_count} profile(s) from Amazon Ads API",
            ))
        except AmazonApiError as exc:
            steps.append(ConnectionTestStep(
                name="profiles_api",
                passed=False,
                detail=str(exc),
            ))
            return ConnectionTestResponse(
                account_id=account.id,
                mode=mode,
                steps=steps,
                profile_count=0,
                error=str(exc),
            )
        except Exception as exc:
            err = f"Profiles API call failed: {exc}"
            steps.append(ConnectionTestStep(
                name="profiles_api",
                passed=False,
                detail=err,
            ))
            return ConnectionTestResponse(
                account_id=account.id,
                mode=mode,
                steps=steps,
                profile_count=0,
                error=err,
            )

        return ConnectionTestResponse(
            account_id=account.id,
            mode=mode,
            steps=steps,
            profile_count=profile_count,
            error=None,
        )

    def delete_account(self, account: SellerAccount) -> None:
        """
        Hard-delete a seller account and all associated data.

        The SellerAccount model has cascade="all, delete-orphan" on both
        credential and profiles relationships, so SQLAlchemy handles
        cascading deletes automatically.
        """
        self.db.delete(account)
        self.db.commit()
