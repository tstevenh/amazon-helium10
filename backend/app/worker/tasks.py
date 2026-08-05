"""Background Amazon sync tasks.

Ported from the daemon thread previously in campaigns/router.py. Two things
changed: job state is persisted in sync_jobs rather than a process-local
dict, and the task can run for hours because nothing is holding an HTTP
connection open. A 30-day sync was measured at 51 minutes; a 2-day sync at
29 minutes. Neither fits inside a web request.
"""
import logging
import traceback
import uuid

from app.database import SessionLocal
from app.modules.accounts.repository import SellerAccountRepository
from app.modules.campaigns.service import CampaignSyncService
from app.modules.sync_jobs.repository import SyncJobRepository
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="sync_account", bind=True)
def sync_account(self, job_id: str, account_id: str, perf_days: int | None = None) -> dict:
    """Full sync: campaign/ad group/target structure, then performance.

    Args:
        job_id:     sync_jobs row to report progress into.
        account_id: SellerAccount UUID as a string (Celery args are JSON).
        perf_days:  Days of performance history; None uses the service default.
    """
    # Imported here to avoid a circular import at module load.
    from app.modules.performance.service import PerformanceService

    job_uuid = uuid.UUID(job_id)
    account_uuid = uuid.UUID(account_id)

    db = SessionLocal()
    jobs = SyncJobRepository(db)
    try:
        jobs.mark_running(job_uuid)

        account = SellerAccountRepository(db).get_by_id(account_uuid)
        if account is None:
            raise ValueError(f"Seller account {account_uuid} not found")

        # ── Structure ──────────────────────────────────────────────────
        result = CampaignSyncService(db).sync_all(account)
        logger.warning("[worker] structure sync done for account %s", account_uuid)

        # ── Performance (non-fatal: keep structure results either way) ──
        perf_rows: dict = {
            "perf_campaign_rows": 0,
            "perf_ad_group_rows": 0,
            "perf_target_rows": 0,
        }
        try:
            perf = PerformanceService(db).sync_performance(
                account, days=perf_days, force_full=True
            )
            perf_rows["perf_campaign_rows"] = perf.campaign_rows
            perf_rows["perf_ad_group_rows"] = perf.ad_group_rows
            perf_rows["perf_target_rows"] = perf.target_rows
            logger.warning(
                "[worker] perf sync done camp=%d ag=%d tgt=%d",
                perf.campaign_rows, perf.ad_group_rows, perf.target_rows,
            )
        except Exception as perf_exc:
            logger.error("[worker] perf sync failed (non-fatal): %s", perf_exc)
            perf_rows["perf_error"] = str(perf_exc)

        if not isinstance(result, dict):
            result = {"structure": result}
        result.update(perf_rows)

        # Surface Plan 1's per-level errors[] at the top level so
        # mark_completed can downgrade the job status to 'partial' rather
        # than reporting an incomplete sync as a success.
        collected: list[str] = []
        for level in ("campaigns", "ad_groups", "targets"):
            section = result.get(level)
            if isinstance(section, dict):
                collected.extend(section.get("errors") or [])
        if perf_rows.get("perf_error"):
            collected.append(f"performance: {perf_rows['perf_error']}")
        result["errors"] = collected

        records = sum(
            (result.get(level) or {}).get("upserted", 0)
            for level in ("campaigns", "ad_groups", "targets")
            if isinstance(result.get(level), dict)
        )
        jobs.mark_completed(job_uuid, result, records)
        logger.warning(
            "[worker] sync_account DONE job=%s records=%d errors=%d",
            job_id, records, len(collected),
        )
        return result

    except Exception as exc:
        logger.error("[worker] sync_account FAILED job=%s: %s\n%s",
                     job_id, exc, traceback.format_exc())
        try:
            db.rollback()
        except Exception:
            pass
        # Record the failure before re-raising so the job never sticks in
        # 'running' — the exact failure mode the in-memory dict had.
        jobs.mark_failed(job_uuid, f"{type(exc).__name__}: {exc}")
        raise
    finally:
        db.close()
