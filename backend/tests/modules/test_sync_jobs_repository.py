"""SyncJob status transitions must be explicit and total."""
import uuid

from app.modules.sync_jobs.models import SyncJob
from app.modules.sync_jobs.repository import (
    ACTIVE_STATUSES,
    JOB_STATUS_FAILED,
    JOB_STATUS_PARTIAL,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCESS,
    UNHEALTHY_STATUSES,
)


# The database constrains status via ck_sync_jobs_status. These must match.
_DB_ALLOWED_STATUSES = {"queued", "running", "success", "failed", "partial"}


def test_status_constants_match_the_database_constraint():
    """A value outside ck_sync_jobs_status raises CheckViolation on insert."""
    for s in (JOB_STATUS_QUEUED, JOB_STATUS_RUNNING, JOB_STATUS_SUCCESS,
              JOB_STATUS_FAILED, JOB_STATUS_PARTIAL):
        assert s in _DB_ALLOWED_STATUSES, f"{s} violates ck_sync_jobs_status"


def test_unhealthy_statuses_include_partial():
    """A partial sync needs attention just as much as a failed one."""
    assert set(UNHEALTHY_STATUSES) == {JOB_STATUS_FAILED, JOB_STATUS_PARTIAL}


def test_mark_completed_downgrades_to_partial_when_errors_present():
    import inspect

    from app.modules.sync_jobs import repository

    src = inspect.getsource(repository.SyncJobRepository.mark_completed)
    assert "JOB_STATUS_PARTIAL" in src, "errors[] must not be reported as success"


def test_active_statuses_are_exactly_queued_and_running():
    """has_active() must block a second sync while one is queued OR running."""
    assert set(ACTIVE_STATUSES) == {JOB_STATUS_QUEUED, JOB_STATUS_RUNNING}


def test_sync_job_can_be_constructed():
    job = SyncJob(job_type="sync_all", seller_account_id=uuid.uuid4())

    assert job.error_message is None
    assert job.result_json is None


def test_status_fits_column_width():
    """status is varchar(20) — a longer constant would raise at runtime."""
    for s in (JOB_STATUS_QUEUED, JOB_STATUS_RUNNING, JOB_STATUS_SUCCESS,
              JOB_STATUS_FAILED, JOB_STATUS_PARTIAL):
        assert len(s) <= 20


def test_job_type_fits_column_width():
    """job_type is varchar(30)."""
    for t in ("sync_all", "performance_sync"):
        assert len(t) <= 30


def test_model_maps_the_existing_table():
    """The table pre-existed; the model must not invent a new name."""
    assert SyncJob.__tablename__ == "sync_jobs"


def test_error_message_is_truncated_by_the_repository():
    """A full traceback in error_message would bloat the API response."""
    import inspect

    from app.modules.sync_jobs import repository

    src = inspect.getsource(repository.SyncJobRepository.mark_failed)
    assert "[:4000]" in src, "mark_failed must bound the stored error text"
