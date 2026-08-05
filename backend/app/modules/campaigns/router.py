"""
Campaigns router — Sprint 1C / Sprint 4B.

sync-all enqueues a Celery task and returns 202 immediately with a job_id.
The worker runs structure sync (campaigns/adgroups/targets) then performance
sync, writing progress to the sync_jobs table. GET sync-status lets the
frontend poll until running=false; because job state is in Postgres it
survives restarts and is visible across API workers.
"""
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.modules.accounts.repository import SellerAccountRepository
from app.modules.audit_log.repository import AuditLogRepository
from app.modules.sync_jobs.repository import ACTIVE_STATUSES, SyncJobRepository
from app.worker.tasks import sync_account
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

    # Job state comes from sync_jobs, so it survives restarts and is visible
    # across API workers. `running` keeps its original meaning and name — the
    # account detail page already polls and reads it.
    job = SyncJobRepository(db).latest_for_account(account_id)

    return JSONResponse(content={
        "campaigns": {"count": int(row.campaign_count or 0), "last_synced_at": _iso(row.campaign_last_at)},
        "ad_groups": {"count": int(row.ad_group_count or 0), "last_synced_at": _iso(row.ad_group_last_at)},
        "targets":   {"count": int(row.target_count or 0),   "last_synced_at": _iso(row.target_last_at)},
        "sync_job": {
            "job_id":         str(job.id) if job else None,
            "running":        job.status in ACTIVE_STATUSES if job else False,
            "status":         job.status if job else None,
            "started_at":     _iso(job.started_at) if job else None,
            "completed_at":   _iso(job.finished_at) if job else None,
            "error":          job.error_message if job else None,
            "result":         job.result_json if job else None,
            "records_synced": job.records_synced if job else 0,
        },
    })


@sync_router.post("/{account_id}/sync-all")
def sync_all(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> JSONResponse:
    """
    Enqueue a full sync (structure + performance) and return immediately.

    Returns 202 with a job_id. Poll GET /accounts/{id}/sync-status for
    progress. Returns 409 if a sync is already queued or running for this
    account — checked against the sync_jobs table, so the guard holds across
    API workers and container restarts.

    A 30-day sync was measured at 51 minutes, so this must not be awaited
    inside a request: the Next.js proxy gives up at 20 minutes and the
    browser far sooner.
    """
    _get_account_or_404(account_id, db)

    jobs = SyncJobRepository(db)
    if jobs.has_active(account_id):
        return JSONResponse(
            status_code=409,
            content={"detail": "Sync already queued or running for this account"},
        )

    job = jobs.create(job_type="sync_all", seller_account_id=account_id)
    sync_account.delay(str(job.id), str(account_id))

    _audit(db, current_user.id, account_id, "sync_all_enqueued", {"job_id": str(job.id)})
    logger.warning("[sync_all] enqueued job %s for account %s", job.id, account_id)

    return JSONResponse(status_code=202, content={
        "message": "Sync queued — poll GET /accounts/{id}/sync-status for progress",
        "status": "queued",
        "job_id": str(job.id),
    })
