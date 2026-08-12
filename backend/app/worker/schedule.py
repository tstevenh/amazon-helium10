"""Periodic sync fan-out.

Beat runs this on an interval; it enqueues one sync_account task per
connected seller account. Accounts that already have a queued or running
job are skipped — a full sync can take hours (30 days measured at 51
minutes), and re-queueing one still in flight would pile up work
indefinitely.
"""
import logging

from app.database import SessionLocal
from app.modules.accounts.models import Credential, SellerAccount
from app.modules.sync_jobs.repository import SyncJobRepository
from app.worker.celery_app import celery_app
from app.worker.tasks import sync_account

logger = logging.getLogger(__name__)


@celery_app.task(name="enqueue_scheduled_syncs")
def enqueue_scheduled_syncs() -> dict:
    """Enqueue a sync for every connected account that is not already syncing."""
    db = SessionLocal()
    try:
        jobs = SyncJobRepository(db)
        # Only accounts that completed OAuth can sync at all.
        accounts = (
            db.query(SellerAccount)
            .join(Credential, Credential.seller_account_id == SellerAccount.id)
            .all()
        )

        enqueued = 0
        skipped = 0
        for account in accounts:
            if jobs.has_active(account.id):
                logger.info("[beat] skipping account %s — sync already active", account.id)
                skipped += 1
                continue
            job = jobs.create(job_type="sync_all", seller_account_id=account.id)
            sync_account.delay(str(job.id), str(account.id))
            logger.warning("[beat] enqueued job %s for account %s", job.id, account.id)
            enqueued += 1

        logger.warning("[beat] scheduled sync fan-out: enqueued=%d skipped=%d",
                       enqueued, skipped)
        return {"enqueued": enqueued, "skipped": skipped}
    finally:
        db.close()
