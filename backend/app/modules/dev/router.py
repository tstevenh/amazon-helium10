"""
Dev bootstrap router — active only when AMAZON_MOCK_MODE=true.

POST /dev/bootstrap-demo-data
    Creates a full mock dataset from scratch (idempotent):
      account → credentials → profiles → campaigns → ad groups →
      targets → search terms → suggestions

Returns 404 when AMAZON_MOCK_MODE=false so it is invisible in production.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone as tz
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.core.encryption import encrypt
from app.database import get_db
from app.dependencies import get_current_user
from app.modules.accounts.repository import (
    AdsProfileRepository,
    CredentialRepository,
    SellerAccountRepository,
)
from app.modules.accounts.service import AccountService
from app.modules.auth.models import User
from app.modules.campaigns.service import CampaignSyncService
from app.modules.search_terms.service import SearchTermSyncService
from app.modules.suggestions.service import SuggestionEngine

dev_router = APIRouter(prefix="/dev", tags=["dev"])

_DEMO_ACCOUNT_NAME = "Demo Account (Mock)"
_MOCK_ACCESS_TOKEN = "mock-access-token-bootstrap"
_MOCK_REFRESH_TOKEN = "mock-refresh-token-bootstrap"


def _guard_mock() -> None:
    if not settings.amazon_mock_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@dev_router.post("/bootstrap-demo-data")
def bootstrap_demo_data(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Idempotent one-shot bootstrap for local/mock development.

    Safe to call multiple times — will not create duplicate data.
    """
    _guard_mock()

    account_repo = SellerAccountRepository(db)
    cred_repo = CredentialRepository(db)
    profile_repo = AdsProfileRepository(db)

    # ── 1. Find or create demo account ────────────────────────────────────
    demo_account = next(
        (a for a in account_repo.list_all() if a.name == _DEMO_ACCOUNT_NAME),
        None,
    )
    if demo_account is None:
        demo_account = account_repo.create(
            name=_DEMO_ACCOUNT_NAME, created_by=user.id
        )
        db.flush()

    account_id = demo_account.id

    # ── 2. Upsert mock credentials (idempotent) ───────────────────────────
    cred_repo.upsert(
        seller_account_id=account_id,
        refresh_token_encrypted=encrypt(_MOCK_REFRESH_TOKEN),
        access_token_encrypted=encrypt(_MOCK_ACCESS_TOKEN),
        token_expires_at=datetime.now(tz.utc) + timedelta(hours=24),
        created_by=user.id,
    )
    db.flush()

    # ── 3. Sync mock profiles (US + CA) ───────────────────────────────────
    # _do_sync_profiles takes the access token directly, bypassing get_valid_access_token
    account_svc = AccountService(db)
    profiles = account_svc._do_sync_profiles(demo_account, _MOCK_ACCESS_TOKEN)
    db.flush()
    profile_ids = [p.id for p in profiles]

    # ── 4. Sync campaigns → ad groups → targets ───────────────────────────
    # sync_all uses get_valid_access_token internally; credentials are now in DB
    campaign_svc = CampaignSyncService(db)
    sync_result = campaign_svc.sync_all(demo_account)
    db.flush()

    # ── 5. Sync mock search terms ─────────────────────────────────────────
    # sync_for_account internally commits; re-query account after to be safe
    st_svc = SearchTermSyncService(db)
    st_result = st_svc.sync_for_account(demo_account)
    # st_svc committed — re-fetch demo_account to avoid detached instance
    demo_account = account_repo.get_by_id(account_id)

    # ── 6. Generate suggestions for each profile ──────────────────────────
    engine = SuggestionEngine(db)
    total_suggestions = 0
    for pid in profile_ids:
        total_suggestions += engine.generate_for_profile(
            profile_id=pid, user_id=user.id
        )
    db.commit()

    # ── Build counts from sync_result ─────────────────────────────────────
    c_res = sync_result.get("campaigns", {})
    ag_res = sync_result.get("ad_groups", {})
    t_res = sync_result.get("targets", {})

    return {
        "status": "ok",
        "account_id": str(account_id),
        "account_name": _DEMO_ACCOUNT_NAME,
        "profiles_synced": len(profiles),
        "campaigns_upserted": c_res.get("upserted", 0),
        "ad_groups_upserted": ag_res.get("upserted", 0),
        "targets_upserted": t_res.get("upserted", 0),
        "search_terms_synced": st_result.get("terms_synced", 0),
        "suggestions_generated": total_suggestions,
    }
