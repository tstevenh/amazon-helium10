"""suggestion_actions is append-only; change_log is the rollback source."""
import inspect

from app.modules.execution import repository as repo_mod
from app.modules.execution.models import ChangeLog, SuggestionAction
from app.modules.execution.repository import (
    ACTION_EXECUTED,
    ACTION_EXECUTION_FAILED,
    ACTION_ROLLED_BACK,
    ENTITY_TARGET,
    ExecutionRepository,
    SOURCE_ROLLBACK,
    SOURCE_SUGGESTION_EXECUTION,
)

# Mirrors ck_suggestion_actions_action and ck_change_log_source in the DB.
_DB_ALLOWED_ACTIONS = {
    "created", "approved", "rejected", "deferred",
    "executed", "execution_failed", "expired", "rolled_back",
}
_DB_ALLOWED_SOURCES = {"suggestion_execution", "manual_edit", "rollback"}
_DB_ALLOWED_ENTITY_TYPES = {"campaign", "ad_group", "target"}


def test_action_constants_match_the_database_constraint():
    """A value outside the check constraint raises CheckViolation on insert."""
    for name, value in vars(repo_mod).items():
        if name.startswith("ACTION_"):
            assert value in _DB_ALLOWED_ACTIONS, f"{name}={value} violates the constraint"


def test_source_constants_match_the_database_constraint():
    for name, value in vars(repo_mod).items():
        if name.startswith("SOURCE_"):
            assert value in _DB_ALLOWED_SOURCES, f"{name}={value} violates the constraint"


def test_entity_type_constants_match_the_database_constraint():
    for name, value in vars(repo_mod).items():
        if name.startswith("ENTITY_"):
            assert value in _DB_ALLOWED_ENTITY_TYPES, f"{name}={value} violates the constraint"


def test_constants_fit_their_column_widths():
    for value in _DB_ALLOWED_ACTIONS:
        assert len(value) <= 30      # action varchar(30)
    for value in _DB_ALLOWED_SOURCES:
        assert len(value) <= 30      # source varchar(30)
    for value in _DB_ALLOWED_ENTITY_TYPES:
        assert len(value) <= 20      # entity_type varchar(20)


def test_repository_has_no_way_to_update_an_attempt():
    """Append-only is enforced by not offering the capability.

    Spec: 'Append-only — never delete or update.' An attempt that could be
    overwritten would destroy the evidence of what actually happened.
    """
    methods = [m for m in dir(ExecutionRepository) if not m.startswith("_")]
    for forbidden in ("update_attempt", "delete_attempt", "edit_attempt"):
        assert forbidden not in methods


def test_record_attempt_only_inserts():
    src = inspect.getsource(ExecutionRepository.record_attempt)
    assert "self.db.add(" in src
    assert ".delete(" not in src


def test_mark_rolled_back_does_not_rewrite_history():
    """Rollback stamps the original and records a NEW row — it must not edit
    old_value/new_value, or the audit trail becomes a lie."""
    src = inspect.getsource(ExecutionRepository.mark_rolled_back)
    assert "rolled_back_at" in src
    for field in ("old_value", "new_value", "field_changed"):
        assert f"row.{field} =" not in src


def test_models_map_the_migrated_tables():
    assert SuggestionAction.__tablename__ == "suggestion_actions"
    assert ChangeLog.__tablename__ == "change_log"


def test_change_log_keeps_the_amazon_id_too():
    """A rollback must be able to address Amazon even if the local row was
    soft-deleted after the change."""
    assert hasattr(ChangeLog, "amazon_entity_id")
