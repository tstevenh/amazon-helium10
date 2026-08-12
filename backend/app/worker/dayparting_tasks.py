"""Hourly dayparting reconciliation.

Runs every hour rather than firing at window edges. See the design note in
app/modules/dayparting/service.py: this host is not reliably awake, and an
edge-triggered scheduler that misses a 6pm "enable" leaves the ads off until a
human notices. Reconciliation self-heals — the worst case is being wrong for
up to one interval.

The interval is therefore also the error bound. An hour is the natural choice
because dayparting windows are expressed in whole hours.
"""
import logging

from app.database import SessionLocal
from app.modules.dayparting.service import DaypartingService
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="reconcile_dayparting")
def reconcile_dayparting() -> dict:
    """Bring every active schedule's campaigns to their scheduled state."""
    db = SessionLocal()
    try:
        summary = DaypartingService(db).reconcile_all_active()
        # warning level so it lands in the same stream as the other scheduled
        # work; an operator reading logs wants to see this without raising
        # verbosity.
        logger.warning(
            "[dayparting] %d schedules: %d checked, %d changed, %d skipped, %d failed",
            summary["schedules"], summary["checked"], summary["changed"],
            summary["skipped"], summary["failed"],
        )
        return summary
    finally:
        db.close()
