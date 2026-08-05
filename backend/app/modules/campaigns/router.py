"""
Campaigns router — Sprint 1C / Sprint 4B.

sync-all is fire-and-forget: POST returns 202 immediately, backend runs
structure sync (campaigns/adgroups/targets) THEN performance sync in a
daemon thread. GET sync-status lets the frontend poll until running=false.
"""
import logging
import threading
import traceback as _tb
import uuid
from datetime import datetime, timezone as tz
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.dependencies import get_current_user, require_admin
from app.modules.accounts.repository import SellerAccountRepository
from app.modules.audit_log.repository import AuditLogRepository
from app.modules.campaigns.repository import (
    AdGroupRepository,
    CampaignRepository,
    TargetRepository,
)
from app.modules.campaigns.schemas import (
    AdGroupResponse,
    CampaignResponse,
    TargetResponse,
)
from app.modules.campaigns.service import CampaignSyncService
from app.modules.auth.models import User
from sqlalchemy import text as _sa_text

logger = logging.getLogger(__name__)

campaigns_router = APIRouter(prefix="/campaigns", tags=["campaigns"])
ad_groups_router = APIRouter(prefix="/ad-groups", tags=["ad-groups"])
targets_router   = APIRouter(prefix="/targets",   tags=["targets"])
sync_router      = APIRouter(prefix="/accounts",  tags=["sync"])

# ── In-memory sync job state ────────────────────────────────────────────────
_sync_jobs: dict[str, dict] = {}
_sync_lock = threading.Lock()


# ── Helper ────────────────────────────────────────────────────────────────

def _get_account_or_404(account_id: uuid.UUID, db: Session):
    account = SellerAccountRepository(db).get_by_id(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"Seller account {account_id} not found")
    return account


def _audit(db: Session, user_id, account_id: uuid.UUID, action: str, extra: dict) -> None:
    try:
        AuditLogRepository(db).create(
            user_id=user_id,
            entity_type="seller_account",
            entity_id=account_id,
            action=action,
            extra_data=extra,
        )
        db.commit()
    except Exception as exc:
        logger.warning("[audit] Failed (action=%s account=%s): %s", action, account_id, exc)
        try:
            db.rollback()
        except Exception:
            pass


# ── Background sync runner ─────────────────────────────────────────────────

def _run_sync_background(account_id_str: str, user_id, account_id: uuid.UUID) -> None:
    """
    Full sync in a daemon thread:
    1. Sync structure (campaigns / ad groups / targets) from Amazon management API
    2. Sync performance metrics from Amazon Reporting API
    """
    # Lazy import to avoid circular import at module load time
    from app.modules.performance.service import PerformanceService

    started_at = datetime.now(tz.utc).isoformat()
    with _sync_lock:
        _sync_jobs[account_id_str] = {
            "running": True,
            "started_at": started_at,
            "completed_at": None,
            "error": None,
            "result": None,
        }

    db = SessionLocal()
    try:
        account = SellerAccountRepository(db).get_by_id(account_id)
        if account is None:
            raise ValueError(f"Account {account_id} not found in background thread")

        # Step 1: structure sync
        svc = CampaignSyncService(db)
        result = svc.sync_all(account)
        logger.warning("[sync_all_bg] Structure sync DONE for account %s", account_id_str)

        # Step 2: performance metrics sync
        perf_rows = {"perf_campaign_rows": 0, "perf_ad_group_rows": 0, "perf_target_rows": 0}
        try:
            perf_svc = PerformanceService(db)
            perf_result = perf_svc.sync_performance(account, force_full=True)
            perf_rows["perf_campaign_rows"] = perf_result.campaign_rows
            perf_rows["perf_ad_group_rows"] = perf_result.ad_group_rows
            perf_rows["perf_target_rows"]   = perf_result.target_rows
            logger.warning(
                "[sync_all_bg] Perf sync DONE camp=%d ag=%d tgt=%d",
                perf_result.campaign_rows, perf_result.ad_group_rows, perf_result.target_rows,
            )
        except Exception as perf_exc:
            logger.error("[sync_all_bg] Perf sync failed (non-fatal): %s", perf_exc)
            perf_rows["perf_error"] = str(perf_exc)

        if isinstance(result, dict):
            result.update(perf_rows)

        _audit(db, user_id, account_id, "sync_all", result)
        with _sync_lock:
            _sync_jobs[account_id_str] = {
                "running": False,
                "started_at": started_at,
                "completed_at": datetime.now(tz.utc).isoformat(),
                "error": None,
                "result": result,
            }
    except Exception as exc:
        logger.error("[sync_all_bg] Error for account %s: %s\n%s", account_id_str, exc, _tb.format_exc())
        with _sync_lock:
            _sync_jobs[account_id_str] = {
                "running": False,
                "started_at": started_at,
                "completed_at": datetime.now(tz.utc).isoformat(),
                "error": f"{type(exc).__name__}: {exc}",
                "result": None,
            }
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


# ── Campaign endpoints ────────────────────────────────────────────────────

@campaigns_router.get("", response_model=list[CampaignResponse])
def list_campaigns(
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[CampaignResponse]:
    repo = CampaignRepository(db)
    return [CampaignResponse.model_validate(c) for c in repo.list_all(include_deleted=include_deleted)]


@campaigns_router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CampaignResponse:
    repo = CampaignRepository(db)
    c = repo.get_by_id(campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    return CampaignResponse.model_validate(c)


@campaigns_router.get("/{campaign_id}/ad-groups", response_model=list[AdGroupResponse])
def list_campaign_ad_groups(
    campaign_id: uuid.UUID,
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[AdGroupResponse]:
    repo = CampaignRepository(db)
    c = repo.get_by_id(campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    ag_repo = AdGroupRepository(db)
    return [AdGroupResponse.model_validate(ag) for ag in ag_repo.list_by_campaign(campaign_id, include_deleted=include_deleted)]


# ── Ad Group endpoints ────────────────────────────────────────────────────

@ad_groups_router.get("", response_model=list[AdGroupResponse])
def list_ad_groups(
    profile_id: Optional[uuid.UUID] = Query(None),
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[AdGroupResponse]:
    repo = AdGroupRepository(db)
    return [AdGroupResponse.model_validate(ag) for ag in repo.list_all(
        profile_id=profile_id,
        include_deleted=include_deleted,
    )]


@ad_groups_router.get("/{ad_group_id}", response_model=AdGroupResponse)
def get_ad_group(
    ad_group_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdGroupResponse:
    repo = AdGroupRepository(db)
    ag = repo.get_by_id(ad_group_id)
    if ag is None:
        raise HTTPException(status_code=404, detail=f"Ad group {ad_group_id} not found")
    return AdGroupResponse.model_validate(ag)


# ── Target endpoints ──────────────────────────────────────────────────────

@targets_router.get("", response_model=list[TargetResponse])
def list_targets(
    target_kind: Optional[str] = Query(None),
    ad_group_id: Optional[uuid.UUID] = Query(None),
    profile_id: Optional[uuid.UUID] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=10000),
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[TargetResponse]:
    repo = TargetRepository(db)
    return [TargetResponse.model_validate(t) for t in repo.list_all(
        target_kind=target_kind,
        ad_group_id=ad_group_id,
        profile_id=profile_id,
        limit=limit,
        include_deleted=include_deleted,
    )]


@targets_router.get("/{target_id}", response_model=TargetResponse)
def get_target(
    target_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TargetResponse:
    repo = TargetRepository(db)
    t = repo.get_by_id(target_id)
    if t is None:
        raise HTTPException(status_code=404, detail=f"Target {target_id} not found")
    return TargetResponse.model_validate(t)


# ── Sync endpoints ────────────────────────────────────────────────────────

@sync_router.post("/{account_id}/campaigns/sync")
def sync_campaigns(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> JSONResponse:
    account = _get_account_or_404(account_id, db)
    svc = CampaignSyncService(db)
    try:
        result = svc.sync_campaigns(account)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Campaign sync failed: {exc}")
    _audit(db, current_user.id, account.id, "sync_campaigns", result)
    return JSONResponse(content={"message": "Campaign sync complete", "campaigns": result})


@sync_router.post("/{account_id}/ad-groups/sync")
def sync_ad_groups(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> JSONResponse:
    account = _get_account_or_404(account_id, db)
    svc = CampaignSyncService(db)
    try:
        result = svc.sync_ad_groups(account)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ad group sync failed: {exc}")
    _audit(db, current_user.id, account.id, "sync_ad_groups", result)
    return JSONResponse(content={"message": "Ad group sync complete", "ad_groups": result})


@sync_router.post("/{account_id}/targets/sync")
def sync_targets(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> JSONResponse:
    account = _get_account_or_404(account_id, db)
    svc = CampaignSyncService(db)
    try:
        result = svc.sync_targets(account)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Target sync failed: {exc}")
    _audit(db, current_user.id, account.id, "sync_targets", result)
    return JSONResponse(content={"message": "Target sync complete", "targets": result})


@sync_router.get("/{account_id}/sync-status")
def get_sync_status(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> JSONResponse:
    _get_account_or_404(account_id, db)

    # Disable statement_timeout for this aggregation — on large accounts the
    # target_stats subquery joins 231K+ targets through campaigns/ad_groups
    # and exceeds the default PostgreSQL statement_timeout.
    # SET LOCAL applies only to the current transaction and resets automatically.
    db.execute(_sa_text("SET LOCAL statement_timeout = 0"))

    row = db.execute(_sa_text("""
        WITH profile_ids AS (
            SELECT id FROM ads_profiles WHERE seller_account_id = :aid
        ),
        campaign_stats AS (
            SELECT COUNT(*) AS cnt, MAX(last_synced_at) AS last_at
            FROM campaigns WHERE profile_id IN (SELECT id FROM profile_ids) AND deleted_at IS NULL
        ),
        ad_group_stats AS (
            SELECT COUNT(*) AS cnt, MAX(ag.last_synced_at) AS last_at
            FROM ad_groups ag JOIN campaigns c ON ag.campaign_id = c.id
            WHERE c.profile_id IN (SELECT id FROM profile_ids) AND ag.deleted_at IS NULL
        ),
        target_stats AS (
            SELECT COUNT(*) AS cnt, MAX(t.last_synced_at) AS last_at
            FROM targets t JOIN ad_groups ag ON t.ad_group_id = ag.id
            JOIN campaigns c ON ag.campaign_id = c.id
            WHERE c.profile_id IN (SELECT id FROM profile_ids) AND t.deleted_at IS NULL
        )
        SELECT
            (SELECT cnt    FROM campaign_stats)  AS campaign_count,
            (SELECT last_at FROM campaign_stats) AS campaign_last_at,
            (SELECT cnt    FROM ad_group_stats)  AS ad_group_count,
            (SELECT last_at FROM ad_group_stats) AS ad_group_last_at,
            (SELECT cnt    FROM target_stats)    AS target_count,
            (SELECT last_at FROM target_stats)   AS target_last_at
    """), {"aid": str(account_id)}).fetchone()

    def _iso(ts):
        return ts.isoformat() if ts else None

    with _sync_lock:
        job = dict(_sync_jobs.get(str(account_id), {}))

    return JSONResponse(content={
        "campaigns": {"count": int(row.campaign_count or 0), "last_synced_at": _iso(row.campaign_last_at)},
        "ad_groups": {"count": int(row.ad_group_count or 0), "last_synced_at": _iso(row.ad_group_last_at)},
        "targets":   {"count": int(row.target_count or 0),   "last_synced_at": _iso(row.target_last_at)},
        "sync_job": {
            "running":      job.get("running", False),
            "started_at":   job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "error":        job.get("error"),
            "result":       job.get("result"),
        },
    })


@sync_router.post("/{account_id}/sync-all")
def sync_all(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> JSONResponse:
    """
    Fire-and-forget full sync (structure + performance). Returns 202 immediately.
    Returns 409 if a sync is already running for this account.
    """
    account_id_str = str(account_id)

    with _sync_lock:
        if _sync_jobs.get(account_id_str, {}).get("running"):
            return JSONResponse(
                status_code=409,
                content={"detail": "Sync already in progress for this account"},
            )

    _get_account_or_404(account_id, db)

    thread = threading.Thread(
        target=_run_sync_background,
        args=(account_id_str, current_user.id, account_id),
        daemon=True,
        name=f"sync-{account_id_str[:8]}",
    )
    thread.start()
    logger.warning("[sync_all] Background thread started for account %s", account_id_str)

    return JSONResponse(status_code=202, content={
        "message": "Sync started — poll GET /accounts/{id}/sync-status for progress",
        "status": "running",
    })
