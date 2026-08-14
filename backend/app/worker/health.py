"""Sync health checks and failure alerting.

Introducing a scheduler without this recreates the original failure mode:
syncs failing invisibly and being discovered weeks later. Two conditions are
watched — jobs that ended unhealthy, and accounts that have not succeeded
recently. A sync that silently never runs is as damaging as one that errors.
"""
import logging
from datetime import datetime, timedelta, timezone as tz

import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.modules.accounts.models import Credential, SellerAccount
from app.modules.sync_jobs.models import SyncJob
from app.modules.sync_jobs.repository import (
    ACTIVE_STATUSES,
    JOB_STATUS_FAILED,
    JOB_STATUS_SUCCESS,
    UNHEALTHY_STATUSES,
)
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


def reap_orphaned_jobs(db: Session, orphan_after_hours: int) -> list[dict]:
    """Fail jobs left at queued/running by a worker that died.

    The status machine assumes every job that starts also finishes — some task
    reaches mark_completed or mark_failed. A hard stop (host reboot, OOM kill,
    `docker compose down` mid-sync) breaks that: nothing runs, and the row says
    'running' forever.

    That is not cosmetic. has_active() counts queued|running and the sync
    endpoint refuses to start a second sync while one is active, so a single
    orphan silently blocks every future sync for that account. It also evades
    collect_sync_health below, which only looks at jobs that *ended* unhealthy
    — so the one condition that stops all syncs was the one nothing watched.

    Time is the only safe signal. Reaping on worker startup would be wrong:
    task_acks_late=True requeues in-flight tasks when a worker is lost, so a
    job that is 'running' at boot may legitimately be about to resume. But
    Celery's hard task_time_limit is 6h5m, so past orphan_after_hours (7 by
    default) no live task can still exist, whatever the worker is doing.
    """
    cutoff = datetime.now(tz.utc) - timedelta(hours=orphan_after_hours)
    # started_at is null for a job that was queued and never picked up — a
    # worker that was down when the request arrived. Fall back to created_at
    # so those are reaped too, rather than blocking syncs indefinitely.
    orphans = (
        db.query(SyncJob)
        .filter(
            SyncJob.status.in_(ACTIVE_STATUSES),
            func.coalesce(SyncJob.started_at, SyncJob.created_at) < cutoff,
        )
        .all()
    )
    reaped = []
    for job in orphans:
        age = datetime.now(tz.utc) - (job.started_at or job.created_at)
        job.status = JOB_STATUS_FAILED
        job.finished_at = datetime.now(tz.utc)
        job.error_message = (
            f"Abandoned after {age.total_seconds() / 3600:.1f}h with no worker running. "
            "The worker process stopped before the sync finished — usually a host "
            "reboot or container restart mid-sync. No data was lost; re-run the sync."
        )
        reaped.append({
            "job_id": str(job.id),
            "account_id": str(job.seller_account_id),
            "age_hours": round(age.total_seconds() / 3600, 1),
        })
        logger.warning(
            "[health] reaped orphaned sync job %s (account %s, age %.1fh)",
            job.id, job.seller_account_id, age.total_seconds() / 3600,
        )
    if reaped:
        db.commit()
    return reaped


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
        # Before assessing health, clear jobs whose worker died. Ordering
        # matters: a reaped job becomes 'failed', so this run reports it and
        # alerts on it, instead of it staying invisible at 'running'.
        reaped = reap_orphaned_jobs(db, settings.sync_orphan_after_hours)
        result = collect_sync_health(db, settings.sync_stale_after_hours)
        result["reaped_orphans"] = reaped
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
        # Route through NotificationService rather than send_alert directly:
        # this writes a notification_log row first, so an unconfigured webhook
        # still leaves a record the Notifications screen can show. Alerting
        # existed before and eight failed syncs were still missed, because
        # stderr is not somewhere anyone looks.
        from app.modules.notifications.service import (
            EVENT_SYNC_FAILED, NotificationService,
        )

        body = "\n".join(lines[1:])
        NotificationService(db).notify(
            EVENT_SYNC_FAILED,
            subject=(
                f"Sync health problem: {len(result['failed_recent'])} failed, "
                f"{len(result['stale_accounts'])} stale"
            ),
            body=body,
            payload=result,
        )
        return result
    finally:
        db.close()
