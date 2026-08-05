"""Persistence for background sync job state.

Replaces the in-memory _sync_jobs dict in campaigns/router.py. Because job
state now lives in Postgres, it survives container restarts and is visible
to every API worker and Celery worker — which the dict was not.
"""
import uuid
from datetime import datetime, timezone as tz

from sqlalchemy.orm import Session

from app.modules.sync_jobs.models import SyncJob

# These values are constrained by ck_sync_jobs_status in the database
# (queued | running | success | failed | partial). Do not invent new ones
# without a migration widening that constraint.
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCESS = "success"
JOB_STATUS_FAILED = "failed"
# 'partial' was in the original schema and maps exactly onto Plan 1's
# contract: the sync ran, but Amazon returned an incomplete view.
JOB_STATUS_PARTIAL = "partial"

# A second sync must be refused while one is queued or already running.
ACTIVE_STATUSES = (JOB_STATUS_QUEUED, JOB_STATUS_RUNNING)
# Statuses that mean "a human should look at this".
UNHEALTHY_STATUSES = (JOB_STATUS_FAILED, JOB_STATUS_PARTIAL)


class SyncJobRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, job_type: str, seller_account_id: uuid.UUID) -> SyncJob:
        job = SyncJob(
            job_type=job_type,
            seller_account_id=seller_account_id,
            status=JOB_STATUS_QUEUED,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def _get(self, job_id: uuid.UUID) -> SyncJob | None:
        return self.db.query(SyncJob).filter(SyncJob.id == job_id).one_or_none()

    def mark_running(self, job_id: uuid.UUID) -> SyncJob | None:
        job = self._get(job_id)
        if job is None:
            return None
        job.status = JOB_STATUS_RUNNING
        job.started_at = datetime.now(tz.utc)
        self.db.commit()
        self.db.refresh(job)
        return job

    def mark_completed(self, job_id: uuid.UUID, result: dict, records: int) -> SyncJob | None:
        """Finish a job as 'success', or 'partial' when result carries errors.

        A run that fetched an incomplete view of Amazon is not a success —
        reporting it as one is the exact bug Plan 1 fixed at the API layer.
        """
        job = self._get(job_id)
        if job is None:
            return None
        errors = result.get("errors") or [] if isinstance(result, dict) else []
        job.status = JOB_STATUS_PARTIAL if errors else JOB_STATUS_SUCCESS
        job.finished_at = datetime.now(tz.utc)
        job.result_json = result
        job.records_synced = records
        if errors:
            job.error_message = "; ".join(str(e) for e in errors)[:4000]
        self.db.commit()
        self.db.refresh(job)
        return job

    def mark_failed(self, job_id: uuid.UUID, error: str) -> SyncJob | None:
        job = self._get(job_id)
        if job is None:
            return None
        job.status = JOB_STATUS_FAILED
        job.finished_at = datetime.now(tz.utc)
        # error_message is TEXT, but a full traceback would bloat every
        # sync-status response that surfaces it.
        job.error_message = error[:4000]
        self.db.commit()
        self.db.refresh(job)
        return job

    def latest_for_account(self, seller_account_id: uuid.UUID) -> SyncJob | None:
        return (
            self.db.query(SyncJob)
            .filter(SyncJob.seller_account_id == seller_account_id)
            .order_by(SyncJob.created_at.desc())
            .first()
        )

    def has_active(self, seller_account_id: uuid.UUID) -> bool:
        return (
            self.db.query(SyncJob)
            .filter(
                SyncJob.seller_account_id == seller_account_id,
                SyncJob.status.in_(ACTIVE_STATUSES),
            )
            .count()
            > 0
        )
