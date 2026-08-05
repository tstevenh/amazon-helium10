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
    include=["app.worker.tasks"],
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


@celery_app.task(name="ping")
def ping() -> str:
    """Plumbing check only — not used by application code."""
    return "pong"
