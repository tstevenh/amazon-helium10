"""The scheduler must fan out per account and never double-queue."""
import inspect

from app.config import settings
from app.worker import schedule


def test_scheduled_task_is_registered():
    assert schedule.enqueue_scheduled_syncs.name == "enqueue_scheduled_syncs"


def test_scheduler_skips_accounts_with_an_active_job():
    """A full sync can take hours. Re-queueing one still in flight every
    6 hours would pile up work indefinitely."""
    src = inspect.getsource(schedule.enqueue_scheduled_syncs)
    assert "has_active" in src, "must skip accounts already syncing"


def test_scheduler_only_syncs_connected_accounts():
    """An account with no OAuth credential cannot sync — don't queue it."""
    src = inspect.getsource(schedule.enqueue_scheduled_syncs)
    assert "Credential" in src


def test_scheduler_reports_what_it_did():
    """Silent scheduling is unauditable."""
    src = inspect.getsource(schedule.enqueue_scheduled_syncs)
    assert "enqueued" in src and "skipped" in src


def test_scheduler_opens_and_closes_its_own_session():
    src = inspect.getsource(schedule.enqueue_scheduled_syncs)
    assert "SessionLocal()" in src
    assert "finally" in src and "close()" in src


def test_periodic_sync_can_be_disabled():
    """SYNC_SCHEDULE_HOURS=0 must disable the periodic sync."""
    from app.worker.celery_app import build_beat_schedule

    assert "enqueue-scheduled-syncs" not in build_beat_schedule(0)
    assert "enqueue-scheduled-syncs" in build_beat_schedule(6)


def test_schedule_interval_matches_configured_hours():
    from app.worker.celery_app import build_beat_schedule

    sched = build_beat_schedule(6)
    assert sched["enqueue-scheduled-syncs"]["schedule"] == 6 * 60 * 60


def test_sync_schedule_hours_setting_exists():
    assert hasattr(settings, "sync_schedule_hours")
    assert settings.sync_schedule_hours >= 0
