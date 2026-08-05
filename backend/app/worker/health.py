"""Sync health checks and failure alerting.

Introducing a scheduler without this recreates the original failure mode:
syncs failing invisibly and being discovered weeks later. Two conditions are
watched — jobs that ended unhealthy, and accounts that have not succeeded
recently. A sync that silently never runs is as damaging as one that errors.
"""
import logging
from datetime import datetime, timedelta, timezone as tz

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.modules.accounts.models import Credential, SellerAccount
from app.modules.sync_jobs.models import SyncJob
from app.modules.sync_jobs.repository import JOB_STATUS_SUCCESS, UNHEALTHY_STATUSES
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


def send_alert(message: str) -> bool:
    """POST an alert to the configured webhook.

    Returns True if delivered. When no webhook is configured this logs at
    ERROR and returns False — a missing alert channel must never crash the
    scheduler, but it must also never look like success.
    """
    if not settings.alert_webhook_url:
        logger.error("[health] ALERT (no webhook configured): %s", message)
        return False
    try:
        resp = requests.post(
            settings.alert_webhook_url,
            json={"text": message},
            timeout=15,
        )
        if not resp.ok:
            logger.error("[health] alert webhook returned HTTP %d", resp.status_code)
            return False
        return True
    except Exception as exc:
        logger.error("[health] alert webhook failed: %s", exc)
        return False


def collect_sync_health(db: Session, stale_after_hours: int) -> dict:
    """Return unhealthy jobs and stale accounts. Pure read, no side effects."""
    now = datetime.now(tz.utc)
    since = now - timedelta(hours=24)
    stale_cutoff = now - timedelta(hours=stale_after_hours)

    # 'partial' is included via UNHEALTHY_STATUSES: a sync that fetched an
    # incomplete view of Amazon needs a human just as much as one that threw.
    failed_recent = [
        {
            "job_id": str(j.id),
            "account_id": str(j.seller_account_id),
            "status": j.status,
            "error": (j.error_message or "")[:300],
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        }
        for j in db.query(SyncJob)
        .filter(SyncJob.status.in_(UNHEALTHY_STATUSES), SyncJob.created_at >= since)
        .order_by(SyncJob.created_at.desc())
        .all()
    ]

    stale_accounts = []
    connected = (
        db.query(SellerAccount)
        .join(Credential, Credential.seller_account_id == SellerAccount.id)
        .all()
    )
    for account in connected:
        last_ok = (
            db.query(SyncJob)
            .filter(
                SyncJob.seller_account_id == account.id,
                SyncJob.status == JOB_STATUS_SUCCESS,
            )
            .order_by(SyncJob.finished_at.desc())
            .first()
        )
        if last_ok is None or last_ok.finished_at is None or last_ok.finished_at < stale_cutoff:
            stale_accounts.append({
                "account_id": str(account.id),
                "name": account.name,
                "last_success": last_ok.finished_at.isoformat()
                if last_ok and last_ok.finished_at else None,
            })

    return {
        "failed_recent": failed_recent,
        "stale_accounts": stale_accounts,
        "healthy": not failed_recent and not stale_accounts,
        "stale_after_hours": stale_after_hours,
        "checked_at": now.isoformat(),
    }


@celery_app.task(name="check_sync_health")
def check_sync_health() -> dict:
    """Beat-driven health check. Alerts only when something is wrong."""
    db = SessionLocal()
    try:
        result = collect_sync_health(db, settings.sync_stale_after_hours)
        if result["healthy"]:
            logger.info("[health] sync health OK")
            return result

        # Only alert on real problems — a channel that fires when everything
        # is fine gets muted, and then failures are invisible again.
        lines = ["PPC OS sync health problem:"]
        for f in result["failed_recent"]:
            lines.append(f"  {f['status'].upper()} account={f['account_id']}: {f['error']}")
        for s in result["stale_accounts"]:
            lines.append(
                f"  STALE account={s['name']} last_success={s['last_success']} "
                f"(threshold {result['stale_after_hours']}h)"
            )
        send_alert("\n".join(lines))
        return result
    finally:
        db.close()
