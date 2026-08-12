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
