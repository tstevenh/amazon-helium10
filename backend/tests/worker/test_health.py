"""Sync failures must be actively surfaced, not merely recorded.

Plan 1 made failures visible in API responses and logs. Introducing a
scheduler without alerting recreates the original failure mode: syncs
failing silently and being discovered weeks later.
"""
import inspect

from app.config import settings
from app.worker import health


def test_collect_sync_health_exists():
    assert hasattr(health, "collect_sync_health")


def test_health_reports_both_failures_and_staleness():
    """A sync that never runs is as damaging as one that fails loudly."""
    src = inspect.getsource(health.collect_sync_health)
    assert "failed" in src
    assert "stale" in src


def test_partial_counts_as_unhealthy():
    """A sync that fetched an incomplete view is not a success.

    The database's own status vocabulary includes 'partial'; treating it as
    healthy would hide exactly what Plan 1 set out to expose.
    """
    src = inspect.getsource(health.collect_sync_health)
    assert "UNHEALTHY_STATUSES" in src, "must flag partial as well as failed"


def test_alerting_is_a_no_op_when_no_webhook_configured():
    """Absent config must not crash the scheduler — log and continue."""
    assert hasattr(settings, "alert_webhook_url")
    assert health.send_alert("test message") is False, (
        "no webhook configured must return False, not raise"
    )


def test_healthy_result_sends_no_alert():
    """Do not train the team to ignore the alert channel."""
    src = inspect.getsource(health.check_sync_health)
    assert "healthy" in src, "must only alert when something is actually wrong"
    # The early return on healthy must come before send_alert.
    assert src.index('result["healthy"]') < src.index("send_alert")


def test_health_task_is_registered():
    assert health.check_sync_health.name == "check_sync_health"


def test_health_check_runs_even_when_periodic_sync_is_disabled():
    """A manually-triggered sync can fail just as silently."""
    from app.worker.celery_app import build_beat_schedule

    assert "check-sync-health" in build_beat_schedule(0)
    assert "check-sync-health" in build_beat_schedule(6)


def test_stale_threshold_is_configurable():
    assert settings.sync_stale_after_hours >= 1


def test_health_opens_and_closes_its_own_session():
    src = inspect.getsource(health.check_sync_health)
    assert "SessionLocal()" in src
    assert "finally" in src and "close()" in src


# ── Orphaned job reaping ───────────────────────────────────────────────────
# A worker that dies mid-sync leaves its job at 'running' forever. Because
# has_active() counts queued|running and the sync endpoint refuses to start a
# second sync while one is active, that single row blocks every future sync
# for the account — and collect_sync_health could not see it, because it only
# examines jobs that already ended. A host reboot mid-sync did this in
# production on the first day of use.
import uuid
from datetime import datetime, timedelta, timezone as tz

from app.modules.sync_jobs.repository import (
    ACTIVE_STATUSES, JOB_STATUS_FAILED, JOB_STATUS_RUNNING,
)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.commits = 0

    def query(self, *args, **kwargs):
        return _FakeQuery(self._rows)

    def commit(self):
        self.commits += 1


class _FakeJob:
    def __init__(self, hours_old):
        self.id = uuid.uuid4()
        self.seller_account_id = uuid.uuid4()
        self.status = JOB_STATUS_RUNNING
        self.started_at = datetime.now(tz.utc) - timedelta(hours=hours_old)
        self.created_at = self.started_at
        self.finished_at = None
        self.error_message = None


def test_reap_marks_orphan_failed_and_records_why():
    job = _FakeJob(hours_old=20)
    db = _FakeSession([job])

    reaped = health.reap_orphaned_jobs(db, orphan_after_hours=7)

    assert len(reaped) == 1
    assert job.status == JOB_STATUS_FAILED, "orphan must leave the active set"
    assert job.finished_at is not None
    assert "Abandoned" in job.error_message
    # The operator reading Sync Monitor needs to know it is safe to retry.
    assert "re-run" in job.error_message.lower()
    assert db.commits == 1


def test_reap_commits_nothing_when_there_are_no_orphans():
    db = _FakeSession([])
    assert health.reap_orphaned_jobs(db, orphan_after_hours=7) == []
    assert db.commits == 0, "must not write on the common healthy path"


def test_reap_threshold_exceeds_celery_hard_time_limit():
    """A slow-but-alive sync must never be reaped out from under itself."""
    from app.worker.celery_app import celery_app

    hard_limit_hours = celery_app.conf.task_time_limit / 3600
    assert settings.sync_orphan_after_hours > hard_limit_hours, (
        "reaping earlier than Celery's hard limit could kill a live sync"
    )


def test_reap_falls_back_to_created_at_for_never_started_jobs():
    """A job queued while the worker was down has no started_at."""
    src = inspect.getsource(health.reap_orphaned_jobs)
    assert "coalesce" in src and "created_at" in src, (
        "a queued-but-never-started job must be reapable, or it blocks syncs forever"
    )


def test_reap_covers_queued_as_well_as_running():
    src = inspect.getsource(health.reap_orphaned_jobs)
    assert "ACTIVE_STATUSES" in src, (
        "has_active() blocks on queued too, so reaping only 'running' still deadlocks"
    )
    assert set(ACTIVE_STATUSES) == {"queued", "running"}


def test_health_check_reaps_before_assessing():
    """Order matters: a reaped job should be reported as failed this run."""
    src = inspect.getsource(health.check_sync_health)
    assert src.index("reap_orphaned_jobs") < src.index("collect_sync_health"), (
        "reaping after collection hides the failure for another 30 minutes"
    )
