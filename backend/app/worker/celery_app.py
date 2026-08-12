"""Celery application for background Amazon syncs.

Pool choice: prefork (the default). The codebase uses synchronous
SQLAlchemy + psycopg2, which prefork runs natively. An asyncio worker
(ARQ, or Celery's gevent pool) would require bridging every blocking DB
and HTTP call, for no benefit here — these tasks are long and few, not
numerous and short.

Task time limits are deliberately generous: Amazon report generation was
measured at 23-40 minutes per report on the live account, and a full
90-day sync is 9 reports.
"""
import logging

from celery import Celery

from app.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "ppc_os",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks", "app.worker.schedule", "app.worker.health",
             "app.worker.execution_tasks", "app.worker.rule_tasks",
             "app.worker.dayparting_tasks", "app.worker.notification_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # A full sync is hours, not seconds. soft < hard so the task can
    # record its own failure into sync_jobs before being killed.
    task_soft_time_limit=6 * 60 * 60,
    task_time_limit=6 * 60 * 60 + 300,
    # Never silently run the same account's sync twice in parallel.
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)


def build_beat_schedule(hours: int) -> dict:
    """Return the Beat schedule, or omit periodic sync when disabled.

    Kept as a function so the disabled case is directly testable.
    """
    schedule: dict = {}
    if hours > 0:
        schedule["enqueue-scheduled-syncs"] = {
            "task": "enqueue_scheduled_syncs",
            "schedule": float(hours * 60 * 60),
        }
    if settings.rule_schedule_hours > 0:
        schedule["evaluate-all-rules"] = {
            "task": "evaluate_all_rules",
            "schedule": float(settings.rule_schedule_hours * 60 * 60),
        }
    # The health check runs regardless of whether periodic sync is enabled —
    # a manually-triggered sync can fail just as silently.
    schedule["check-sync-health"] = {
        "task": "check_sync_health",
        "schedule": float(settings.health_check_interval_minutes * 60),
    }
    # Dayparting reconciles rather than firing on window edges, so this
    # interval is the error bound: a missed run leaves campaigns in the wrong
    # state for at most this long. It runs unconditionally — a schedule that
    # only reconciles when some other feature is enabled would be a trap.
    schedule["reconcile-dayparting"] = {
        "task": "reconcile_dayparting",
        "schedule": float(settings.dayparting_interval_minutes * 60),
    }
    # The digest is the one message a day that answers "does anything need me?".
    # It runs even with no webhook configured, because it is also written to
    # notification_log and read by the Notifications screen.
    if settings.digest_interval_hours > 0:
        schedule["send-daily-digest"] = {
            "task": "send_daily_digest",
            "schedule": float(settings.digest_interval_hours * 3600),
        }
    return schedule


celery_app.conf.beat_schedule = build_beat_schedule(settings.sync_schedule_hours)


@celery_app.task(name="ping")
def ping() -> str:
    """Plumbing check only — not used by application code."""
    return "pong"
