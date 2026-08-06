"""Execution must never auto-retry a write to Amazon."""
import inspect

from app.worker import execution_tasks


def test_task_is_registered():
    assert execution_tasks.execute_suggestion.name == "execute_suggestion"


def test_task_never_retries():
    """Celery's default retry would re-issue a write. A duplicated bid change
    is worse than a failed one a human can see and re-approve."""
    assert execution_tasks.execute_suggestion.max_retries == 0


def test_task_does_not_raise_on_business_failure():
    """ExecutionService records execution_failed and returns a result.
    Raising would let Celery treat it as infrastructure failure."""
    src = inspect.getsource(execution_tasks.execute_suggestion)
    assert "return ExecutionService" in src or "return " in src
    # The only raise-equivalent should be inside the except, and it returns.
    assert "raise" not in src


def test_task_opens_and_closes_its_own_session():
    src = inspect.getsource(execution_tasks.execute_suggestion)
    assert "SessionLocal()" in src
    assert "finally" in src and "close()" in src


def test_celery_args_are_json_safe():
    sig = inspect.signature(execution_tasks.execute_suggestion.__wrapped__)
    for name in ("suggestion_id", "user_id"):
        assert sig.parameters[name].annotation is str


def test_approval_does_not_auto_execute():
    """Spec: 'NO auto-apply in V1.' Approving records intent; executing is a
    separate deliberate act."""
    from app.modules.suggestions import router as sugg_router

    src = inspect.getsource(sugg_router)
    assert "execute_suggestion" not in src, (
        "approving must not enqueue execution — that would be auto-apply"
    )


def test_execute_endpoint_refuses_unapproved():
    from app.modules.execution import router as exec_router

    src = inspect.getsource(exec_router.execute)
    assert '"approved"' in src
    assert "409" in src or "HTTP_409_CONFLICT" in src
