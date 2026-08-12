"""Sync job history — the data behind the Sync Monitor screen.

Read-only. Triggering a sync lives in the accounts/campaigns routers; this
exists so failures are visible in the app rather than only in a webhook that
may not be configured.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.sync_jobs.repository import SyncJobRepository

router = APIRouter(prefix="/sync-jobs", tags=["sync-jobs"])


@router.get("")
def list_sync_jobs(
    limit: int = Query(50, le=200),
    account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    jobs = SyncJobRepository(db).recent(
        limit=limit,
        account_id=uuid.UUID(account_id) if account_id else None,
    )
    return {
        "stale_after_hours": settings.sync_stale_after_hours,
        "schedule_hours": settings.sync_schedule_hours,
        "jobs": [
            {
                "id": str(j.id),
                "job_type": j.job_type,
                "seller_account_id": str(j.seller_account_id),
                "status": j.status,
                "records_synced": j.records_synced,
                "error_message": j.error_message,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            }
            for j in jobs
        ],
    }
