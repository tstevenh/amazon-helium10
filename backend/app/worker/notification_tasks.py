"""Scheduled notifications.

Spec §4.3 singles this out: "lightweight daily digest — scheduled Slack
message summarizing pending/approved/executed counts. Cheap, high value,
independent of full Notifications subsystem."

It is also the thing that would have surfaced eight consecutive failed syncs
in a day instead of a week.
"""
import logging

from app.database import SessionLocal
from app.modules.notifications.service import NotificationService
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="send_daily_digest")
def send_daily_digest() -> dict:
    """One message a day: what needs attention, and whether data is current."""
    db = SessionLocal()
    try:
        row = NotificationService(db).send_daily_digest()
        logger.warning("[notify] daily digest %s: %s", row.delivery_status, row.subject)
        return {
            "delivery_status": row.delivery_status,
            "subject": row.subject,
            "payload": row.payload,
        }
    finally:
        db.close()
