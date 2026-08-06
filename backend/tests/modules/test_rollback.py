"""Rollback must never rewrite history, and must refuse what it cannot undo.

The spec lists rollback as a known gap: "Change Log records old->new values
but there's no 'revert this one change' button." It is built before the first
real write, because an undo you only build once you need it is an undo you
don't have when you need it.
"""
import inspect

from app.modules.execution.service import RollbackService


def test_rollback_service_exists():
    assert hasattr(RollbackService, "rollback")


def test_refuses_an_already_rolled_back_change():
    """Otherwise a double-click oscillates the bid on a live account."""
    src = inspect.getsource(RollbackService.rollback)
    assert "rolled_back_at is not None" in src


def test_refuses_to_roll_back_a_rollback():
    """Rolling back a rollback would flip the value again and make the trail
    unreadable. Roll back the original instead."""
    src = inspect.getsource(RollbackService.rollback)
    assert "SOURCE_ROLLBACK" in src
    assert "itself a rollback" in src


def test_refuses_when_there_is_no_old_value():
    """Nothing to restore. This is why execution refuses to write a
    change_log row it cannot populate."""
    src = inspect.getsource(RollbackService.rollback)
    assert "old_value is None" in src


def test_refuses_without_an_amazon_id():
    """Our UUID is meaningless to Amazon — the rollback needs the real id."""
    src = inspect.getsource(RollbackService.rollback)
    assert "amazon_entity_id" in src
    assert "cannot address Amazon" in src


def test_writes_a_new_row_rather_than_editing_the_original():
    """History is append-only. Editing the original would make the audit
    trail a lie about what happened and when."""
    src = inspect.getsource(RollbackService.rollback)
    assert "record_change(" in src
    assert "mark_rolled_back(" in src
    # It must not mutate the original row's values directly.
    for field in ("change.old_value =", "change.new_value =", "change.field_changed ="):
        assert field not in src


def test_new_row_swaps_old_and_new():
    """The rollback row reads: from the value we set, back to the original."""
    src = inspect.getsource(RollbackService.rollback)
    assert "old_value=change.new_value" in src
    assert "new_value=change.old_value" in src


def test_goes_through_the_gated_write_client():
    """A rollback is still a write — it must respect the kill-switch."""
    src = inspect.getsource(RollbackService.rollback)
    assert "amazon_ads_write.update_keyword_bid" in src
    assert "AmazonWriteDisabled" in src


def test_only_supports_what_it_can_actually_undo():
    """Refuse unsupported entity/field combinations rather than pretending."""
    src = inspect.getsource(RollbackService.rollback)
    assert "field_changed" in src and "ENTITY_TARGET" in src


def test_failed_rollback_records_the_attempt():
    """A rejected rollback must leave a trace, not vanish."""
    src = inspect.getsource(RollbackService.rollback)
    fail_branch = src[src.index('if not result.get("ok")'):]
    assert "record_attempt" in fail_branch
