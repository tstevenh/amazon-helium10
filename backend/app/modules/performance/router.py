"""
Performance API routes (Sprint 4B).

GET  /performance/campaigns                        — all campaigns + metrics
GET  /performance/campaigns/{id}/summary           — one campaign summary
GET  /performance/campaigns/{id}/ad-groups         — ad groups under a campaign + metrics (bulk)
GET  /performance/ad-groups/{id}/summary           — one ad group summary
GET  /performance/ad-groups/{id}/targets           — targets under an ad group + metrics (bulk)
POST /performance/sync                             — trigger performance sync (manual)
"""
import logging
import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.accounts.repository import SellerAccountRepository, AdsProfileRepository
from app.modules.campaigns.models import AdGroup, Campaign, Target
from app.modules.performance.repository import PerformanceRepository
from app.modules.performance.schemas import (
    CampaignWithMetrics,
    PerfSyncResponse,
    PerfSyncResult,
)
from app.modules.performance.service import PerformanceService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/performance", tags=["performance"])


def _default_dates() -> tuple[date, date]:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=29)
    return start, end


# ── Campaign endpoints ────────────────────────────────────────────────────

@router.get("/campaigns", response_model=list[CampaignWithMetrics])
def get_campaigns_with_metrics(
    date_from: Optional[date] = Query(None),
    date_to:   Optional[date] = Query(None),
    profile_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not date_from or not date_to:
        date_from, date_to = _default_dates()

    perf_repo = PerformanceRepository(db)

    if profile_id:
        campaigns = db.query(Campaign).filter(
            Campaign.profile_id == uuid.UUID(profile_id),
            Campaign.deleted_at.is_(None),
        ).all()
    elif account_id:
        profiles = AdsProfileRepository(db).get_by_account(uuid.UUID(account_id))
        campaigns = []
        for p in profiles:
            campaigns.extend(
                db.query(Campaign).filter(
                    Campaign.profile_id == p.id,
                    Campaign.deleted_at.is_(None),
                ).all()
            )
    else:
        campaigns = db.query(Campaign).filter(Campaign.deleted_at.is_(None)).all()

    camp_ids = [str(c.id) for c in campaigns]
    metrics_map = perf_repo.get_all_campaigns_summary(camp_ids, date_from, date_to)

    result = []
    for c in campaigns:
        m = metrics_map.get(str(c.id))
        result.append(CampaignWithMetrics(
            id=c.id,
            profile_id=c.profile_id,
            name=c.name,
            ad_product=c.ad_product,
            status=c.status,
            daily_budget=c.daily_budget,
            targeting_type=c.targeting_type,
            impressions=m["impressions"] if m else None,
            clicks=m["clicks"] if m else None,
            spend=m["spend"] if m else None,
            sales=m["sales"] if m else None,
            orders=m["orders"] if m else None,
            ctr=m["ctr"] if m else None,
            cpc=m["cpc"] if m else None,
            acos=m["acos"] if m else None,
            roas=m["roas"] if m else None,
        ))
    return result


@router.get("/campaigns/{campaign_id}/summary")
def get_campaign_summary(
    campaign_id: str,
    date_from: Optional[date] = Query(None),
    date_to:   Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not date_from or not date_to:
        date_from, date_to = _default_dates()
    summary = PerformanceRepository(db).get_campaign_summary(campaign_id, date_from, date_to)
    return summary or {}


@router.get("/campaigns/{campaign_id}/ad-groups")
def get_campaign_ad_groups_with_metrics(
    campaign_id: str,
    date_from: Optional[date] = Query(None),
    date_to:   Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all ad groups for a campaign enriched with aggregated metrics."""
    if not date_from or not date_to:
        date_from, date_to = _default_dates()

    ad_groups = db.query(AdGroup).filter(
        AdGroup.campaign_id == uuid.UUID(campaign_id),
        AdGroup.deleted_at.is_(None),
    ).all()

    ag_ids = [str(ag.id) for ag in ad_groups]
    metrics_map = PerformanceRepository(db).get_all_ad_groups_summary(ag_ids, date_from, date_to)

    result = []
    for ag in ad_groups:
        m = metrics_map.get(str(ag.id))
        result.append({
            "id": str(ag.id),
            "campaign_id": str(ag.campaign_id),
            "name": ag.name,
            "status": ag.status,
            "default_bid": float(ag.default_bid) if ag.default_bid is not None else None,
            "impressions": m["impressions"] if m else None,
            "clicks":      m["clicks"]      if m else None,
            "spend":       float(m["spend"]) if m else None,
            "sales":       float(m["sales"]) if m else None,
            "orders":      m["orders"]      if m else None,
            "ctr":         float(m["ctr"])  if m and m["ctr"]  is not None else None,
            "cpc":         float(m["cpc"])  if m and m["cpc"]  is not None else None,
            "acos":        float(m["acos"]) if m and m["acos"] is not None else None,
            "roas":        float(m["roas"]) if m and m["roas"] is not None else None,
        })
    return result


# ── Profile-wide listings (ranked by spend) ───────────────────────────────
#
# The Ad Groups and Keywords screens previously listed names with no metrics
# at all, and the keyword list was capped at 2,000 rows with no ORDER BY — an
# arbitrary 2,000 out of 231,799. These two endpoints return the same shape
# plus metrics, highest spend first, so a capped page shows the rows a PPC
# manager actually needs to look at.

def _resolve_profile_ids(
    db: Session,
    profile_id: Optional[str],
    account_id: Optional[str],
) -> list[str]:
    if profile_id:
        return [profile_id]
    if account_id:
        return [str(p.id) for p in AdsProfileRepository(db).get_by_account(uuid.UUID(account_id))]
    return []


@router.get("/ad-groups")
def get_ad_groups_with_metrics(
    date_from: Optional[date] = Query(None),
    date_to:   Optional[date] = Query(None),
    profile_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    limit: int = Query(2000, le=10000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not date_from or not date_to:
        date_from, date_to = _default_dates()
    profile_ids = _resolve_profile_ids(db, profile_id, account_id)
    if not profile_ids:
        return []
    return PerformanceRepository(db).top_ad_groups_by_spend(
        profile_ids, date_from, date_to, limit=limit,
    )


@router.get("/targets")
def get_targets_with_metrics(
    date_from: Optional[date] = Query(None),
    date_to:   Optional[date] = Query(None),
    profile_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    target_kind: Optional[str] = Query(None),
    limit: int = Query(2000, le=10000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Keywords/product targets + metrics, highest spend first.

    Returns an envelope rather than a bare list so the UI can say
    "showing the top 2,000 of 231,799 by spend" instead of implying the
    account only has 2,000 keywords.
    """
    if not date_from or not date_to:
        date_from, date_to = _default_dates()
    profile_ids = _resolve_profile_ids(db, profile_id, account_id)
    if not profile_ids:
        return {"items": [], "total": 0, "limit": limit}
    repo = PerformanceRepository(db)
    return {
        "items": repo.top_targets_by_spend(
            profile_ids, date_from, date_to, target_kind=target_kind, limit=limit,
        ),
        "total": repo.count_targets(profile_ids, target_kind=target_kind),
        "limit": limit,
    }


# ── Ad group endpoints ────────────────────────────────────────────────────

@router.get("/ad-groups/{ad_group_id}/summary")
def get_ad_group_summary(
    ad_group_id: str,
    date_from: Optional[date] = Query(None),
    date_to:   Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not date_from or not date_to:
        date_from, date_to = _default_dates()
    summary = PerformanceRepository(db).get_ad_group_summary(ad_group_id, date_from, date_to)
    return summary or {}


@router.get("/ad-groups/{ad_group_id}/targets")
def get_ad_group_targets_with_metrics(
    ad_group_id: str,
    date_from: Optional[date] = Query(None),
    date_to:   Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all targets for an ad group enriched with aggregated metrics."""
    if not date_from or not date_to:
        date_from, date_to = _default_dates()

    try:
        ag_uuid = uuid.UUID(ad_group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ad group ID")

    targets = db.query(Target).filter(
        Target.ad_group_id == ag_uuid,
        Target.deleted_at.is_(None),
    ).all()

    target_ids = [str(t.id) for t in targets]
    metrics_map = PerformanceRepository(db).get_all_targets_summary(target_ids, date_from, date_to)

    result = []
    for t in targets:
        m = metrics_map.get(str(t.id))
        result.append({
            "id": str(t.id),
            "ad_group_id": str(t.ad_group_id),
            "amazon_target_id": t.amazon_target_id,
            "target_kind": t.target_kind,
            "expression_type": getattr(t, "expression_type", None),
            "expression_text": t.expression_text,
            "match_type": t.match_type,
            "bid": float(t.bid) if t.bid is not None else None,
            "status": t.status,
            "impressions": m["impressions"] if m else None,
            "clicks":      m["clicks"]      if m else None,
            "spend":       float(m["spend"]) if m else None,
            "sales":       float(m["sales"]) if m else None,
            "orders":      m["orders"]       if m else None,
            "ctr":         float(m["ctr"])   if m and m["ctr"]  is not None else None,
            "cpc":         float(m["cpc"])   if m and m["cpc"]  is not None else None,
            "acos":        float(m["acos"])  if m and m["acos"] is not None else None,
            "roas":        float(m["roas"])  if m and m["roas"] is not None else None,
        })
    return result


# ── Anomalies & placement (Phase 3) ───────────────────────────────────────

@router.get("/anomalies")
def get_anomalies(
    profile_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    recent_days: int = Query(3, ge=1, le=14),
    baseline_days: int = Query(14, ge=5, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """What changed lately, for the Dashboard anomaly panel (spec §13.1)."""
    from app.modules.performance.anomalies import AnomalyDetector

    profile_ids = _resolve_profile_ids(db, profile_id, account_id)
    if not profile_ids:
        return {"anomalies": [], "checked_profiles": 0}
    found = AnomalyDetector(db).detect(
        profile_ids, recent_days=recent_days, baseline_days=baseline_days,
    )
    return {"anomalies": found, "checked_profiles": len(profile_ids)}


@router.get("/placements")
def get_placement_performance(
    date_from: Optional[date] = Query(None),
    date_to:   Optional[date] = Query(None),
    profile_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Spend split by where the ad appeared, per campaign."""
    if not date_from or not date_to:
        date_from, date_to = _default_dates()
    profile_ids = _resolve_profile_ids(db, profile_id, account_id)
    if not profile_ids:
        return {"campaigns": [], "totals": {}}

    campaigns = db.query(Campaign).filter(
        Campaign.profile_id.in_([uuid.UUID(p) for p in profile_ids]),
        Campaign.deleted_at.is_(None),
    ).all()
    repo = PerformanceRepository(db)
    by_campaign = repo.placement_summary(
        [str(c.id) for c in campaigns], date_from, date_to,
    )

    out = []
    totals: dict[str, dict] = {}
    for c in campaigns:
        placements = by_campaign.get(str(c.id))
        if not placements:
            continue
        out.append({
            "campaign_id": str(c.id),
            "campaign_name": c.name,
            "placement_bidding": c.placement_bidding,
            "placements": placements,
        })
        for name, m in placements.items():
            agg = totals.setdefault(name, {"spend": 0.0, "sales": 0.0,
                                           "clicks": 0, "orders": 0})
            agg["spend"] += m["spend"]
            agg["sales"] += m["sales"]
            agg["clicks"] += m["clicks"]
            agg["orders"] += m["orders"]

    for name, agg in totals.items():
        agg["acos"] = (agg["spend"] / agg["sales"] * 100) if agg["sales"] else None
        agg["roas"] = (agg["sales"] / agg["spend"]) if agg["spend"] else None

    # Highest spend first: the placement taking the most money is the one worth
    # looking at, whether it is performing or not.
    out.sort(key=lambda r: -sum(p["spend"] for p in r["placements"].values()))
    return {"campaigns": out, "totals": totals,
            "date_from": date_from.isoformat(), "date_to": date_to.isoformat()}


# ── Manual perf sync ──────────────────────────────────────────────────────

@router.post("/sync", response_model=PerfSyncResponse)
def sync_performance(
    account_id: str = Query(...),
    days: Optional[int] = Query(None),
    force_full: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = SellerAccountRepository(db).get_by_id(uuid.UUID(account_id))
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    try:
        result = PerformanceService(db).sync_performance(account, days=days, force_full=force_full)
    except Exception as exc:
        logger.error("[perf] sync failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return PerfSyncResponse(
        message=(f"Performance sync complete: {result.campaign_rows} campaign rows, "
                 f"{result.ad_group_rows} ad group rows, {result.target_rows} target rows"),
        result=result,
    )
