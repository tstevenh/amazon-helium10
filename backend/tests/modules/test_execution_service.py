"""Execution ordering is the safety property — assert it, don't assume it."""
import inspect

from app.modules.execution.service import ExecutionService


def test_only_approved_suggestions_execute():
    """Spec: 'Mandatory: Rule -> Suggestion -> Human Review -> Apply.
    NO auto-apply in V1.' A pending suggestion has had no human review."""
    src = inspect.getsource(ExecutionService.execute)
    assert "STATUS_APPROVED" in src
    # The guard must come before the Amazon call.
    assert src.index("STATUS_APPROVED") < src.index("update_keyword_bid")


def test_attempt_is_recorded_before_the_api_call():
    """If the process dies mid-call there must still be evidence we tried,
    otherwise a change could exist on Amazon with no record of it here."""
    src = inspect.getsource(ExecutionService.execute)
    assert src.index("record_attempt") < src.index("update_keyword_bid")


def test_failure_writes_no_change_log_row():
    """A change_log row means 'this really changed on Amazon'. Writing one
    for a failed call would make rollback restore a value never set."""
    src = inspect.getsource(ExecutionService._fail)
    assert "record_change" not in src
    assert "ACTION_EXECUTION_FAILED" in src


def test_success_records_both_old_and_new_value():
    """Rollback restores old_value — a change_log row without it is useless."""
    src = inspect.getsource(ExecutionService.execute)
    assert "old_value=" in src
    assert "new_value=" in src


def test_unsupported_suggestion_type_is_refused_not_ignored():
    """An unhandled type must not be marked executed when nothing happened."""
    src = inspect.getsource(ExecutionService.execute)
    assert "_BID_TYPES" in src
    assert "not executable yet" in src


def test_missing_target_or_value_fails_loudly():
    src = inspect.getsource(ExecutionService.execute)
    assert "no target_id" in src
    assert "no suggested_value" in src


def test_kill_switch_failure_is_caught_and_recorded():
    """AmazonWriteDisabled must land as a recorded failure, not a 500."""
    src = inspect.getsource(ExecutionService.execute)
    assert "AmazonWriteDisabled" in src


def test_one_amazon_call_per_execution():
    """Spec: 'One suggestion = one Amazon API write call (no batching in V1).'"""
    src = inspect.getsource(ExecutionService.execute)
    assert src.count("update_keyword_bid(") == 1


def test_executed_at_is_stamped_on_success():
    src = inspect.getsource(ExecutionService.execute)
    assert "executed_at" in src


def test_service_uses_the_gated_write_client_only():
    """Execution must never bypass the kill-switch with a raw request."""
    src = inspect.getsource(inspect.getmodule(ExecutionService))
    assert "amazon_ads_write" in src
    for raw in ("requests.put(", "requests.post(", "requests.patch("):
        assert raw not in src, f"execution must not call {raw} directly"
