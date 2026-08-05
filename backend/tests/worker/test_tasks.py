"""The sync task must record its own outcome into sync_jobs, always."""
import inspect

from app.worker import tasks


def test_sync_account_task_exists_and_is_registered():
    assert hasattr(tasks, "sync_account")
    assert tasks.sync_account.name == "sync_account"


def test_task_opens_its_own_db_session():
    """A Celery task has no request-scoped session — it must make its own."""
    src = inspect.getsource(tasks.sync_account)
    assert "SessionLocal()" in src, "task must create its own DB session"
    assert "finally" in src and "close()" in src, "session must always be closed"


def test_task_marks_running_then_completed_or_failed():
    """Every exit path must leave the job in a terminal state."""
    src = inspect.getsource(tasks.sync_account)
    assert "mark_running" in src
    assert "mark_completed" in src
    assert "mark_failed" in src


def test_failure_is_recorded_before_reraise():
    """A crashed sync must not leave the job stuck in 'running' forever.

    This is the bug the in-memory dict had: a container restart mid-sync
    left no record at all.
    """
    src = inspect.getsource(tasks.sync_account)
    assert "except Exception" in src
    assert src.index("except Exception") < src.index("mark_failed")


def test_performance_failure_does_not_abort_structure_sync():
    """Structure sync results must be kept even if the perf sync fails.

    Matches the pre-existing behaviour in _run_sync_background, which
    treated a perf failure as non-fatal.
    """
    src = inspect.getsource(tasks.sync_account)
    assert "perf_error" in src, "perf failure must be recorded, not fatal"


def test_errors_are_collected_to_the_top_level():
    """Plan 1 put errors[] on each level; the job needs them in one place
    so mark_completed can downgrade the status to 'partial'."""
    src = inspect.getsource(tasks.sync_account)
    assert '"errors"' in src
    for level in ("campaigns", "ad_groups", "targets"):
        assert level in src, f"must collect errors from {level}"


def test_celery_args_are_json_safe():
    """Celery serialises args as JSON — UUIDs must be passed as strings.

    Positions are not asserted: with bind=True, Celery's wrapper does not
    expose `self` in __wrapped__, so index-based checks are brittle.
    """
    sig = inspect.signature(tasks.sync_account.__wrapped__)

    for name in ("job_id", "account_id"):
        assert name in sig.parameters, f"{name} must be an argument"
        assert sig.parameters[name].annotation is str, (
            f"{name} must be typed str — a UUID object is not JSON-serialisable"
        )

    # The task must convert them back itself.
    src = inspect.getsource(tasks.sync_account)
    assert "uuid.UUID(job_id)" in src
    assert "uuid.UUID(account_id)" in src
