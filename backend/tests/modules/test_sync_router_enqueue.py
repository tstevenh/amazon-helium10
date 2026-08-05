"""sync-all must enqueue and return immediately; no threads, no dict."""
import inspect

from app.modules.campaigns import router as campaigns_router


def test_in_memory_job_state_is_gone():
    """The _sync_jobs dict and its lock caused the multi-worker bug: state
    invisible across processes and lost on restart."""
    src = inspect.getsource(campaigns_router)

    assert "_sync_jobs" not in src, "in-memory job dict must be deleted"
    assert "_sync_lock" not in src, "in-memory lock must be deleted"
    assert "import threading" not in src, "threading is no longer used"
    assert "_run_sync_background" not in src, "daemon thread runner must be deleted"


def test_sync_all_enqueues_a_celery_task():
    src = inspect.getsource(campaigns_router.sync_all)

    assert "sync_account" in src, "must enqueue the Celery task"
    assert ".delay(" in src or ".apply_async(" in src, "must dispatch asynchronously"
    assert "202" in src, "must return 202 Accepted immediately"


def test_sync_all_refuses_concurrent_runs_via_database():
    """The 409 guard must consult the DB, not process-local state."""
    src = inspect.getsource(campaigns_router.sync_all)

    assert "has_active" in src, "concurrency guard must query sync_jobs"
    assert "409" in src


def test_sync_all_returns_the_job_id():
    """Without a job id the caller cannot correlate its poll results."""
    src = inspect.getsource(campaigns_router.sync_all)
    assert "job_id" in src


def test_sync_status_reads_job_from_database():
    src = inspect.getsource(campaigns_router.get_sync_status)

    assert "latest_for_account" in src, "status must read the persisted job"
    assert "sync_job" in src, "existing response key must be preserved"


def test_sync_status_preserves_the_running_key_for_the_frontend():
    """The account detail page already polls and reads sync_job.running.
    Renaming it would break the existing UI silently."""
    src = inspect.getsource(campaigns_router.get_sync_status)
    assert '"running"' in src
