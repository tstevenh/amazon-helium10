"""Search terms router (Sprint 2).

Routes:
  GET  /search-terms                          — list aggregated rows for current profile
  POST /accounts/{account_id}/search-terms/sync      — sync + generate suggestions
  POST /accounts/{account_id}/search-terms/sync-all  — alias for sync
"""
from __future__ import annotations
import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.accounts.repository import SellerAccountRepository
from app.modules.search_terms.repository import SearchTermRepository
from app.modules.search_terms.schemas import SearchTermRow, SearchTermSyncResponse
from app.modules.search_terms.service import SearchTermSyncService

search_terms_router = APIRouter(prefix="/search-terms", tags=["search-terms"])
st_sync_router = APIRouter(prefix="/accounts", tags=["search-terms-sync"])


@search_terms_router.get("", response_model=list[SearchTermRow])
def list_search_terms(
    profile_id: uuid.UUID = Query(..., description="Filter by ads_profile ID"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    campaign_id: Optional[uuid.UUID] = Query(None),
    min_spend: Optional[float] = Query(None, ge=0),
    min_sales: Optional[float] = Query(None, ge=0),
    max_acos: Optional[float] = Query(None, ge=0),
    q: Optional[str] = Query(None),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SearchTermRow]:
    today = date.today()
    df = date_from or (today - timedelta(days=30))
    dt = date_to or today
    repo = SearchTermRepository(db)
    rows = repo.get_aggregated(
        profile_id=profile_id,
        date_from=df,
        date_to=dt,
        campaign_id=campaign_id,
        min_spend=min_spend,
        min_sales=min_sales,
        max_acos=max_acos,
        q=q,
    )
    return [SearchTermRow(**r) for r in rows]


def _do_sync(account_id: uuid.UUID, db: Session, user: User) -> dict:
    account = SellerAccountRepository(db).get_by_id(account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    svc = SearchTermSyncService(db)
    result = svc.sync_for_account(account)

    # Auto-generate suggestions after sync
    from app.modules.suggestions.service import SuggestionEngine
    engine = SuggestionEngine(db)
    from app.modules.accounts.repository import AdsProfileRepository
    profiles = AdsProfileRepository(db).get_by_account(account_id)
    total_sugg = 0
    for profile in profiles:
        total_sugg += engine.generate_for_profile(profile.id, user.id)
    db.commit()

    return {
        "terms_synced": result["terms_synced"],
        "suggestions_generated": total_sugg,
    }


@st_sync_router.post("/{account_id}/search-terms/sync", response_model=SearchTermSyncResponse)
def sync_search_terms(
    account_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SearchTermSyncResponse:
    result = _do_sync(account_id, db, user)
    return SearchTermSyncResponse(
        message="Search terms synced successfully",
        account_id=str(account_id),
        **result,
    )


@st_sync_router.post("/{account_id}/search-terms/sync-all", response_model=SearchTermSyncResponse)
def sync_search_terms_all(
    account_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SearchTermSyncResponse:
    result = _do_sync(account_id, db, user)
    return SearchTermSyncResponse(
        message="Search terms sync-all completed",
        account_id=str(account_id),
        **result,
    )
