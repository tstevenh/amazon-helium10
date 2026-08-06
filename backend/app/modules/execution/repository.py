"""Persistence for execution attempts and the change log.

suggestion_actions is append-only by design — there is no update method here,
deliberately. An attempt that was recorded and then overwritten would destroy
the evidence of what actually happened, which is the whole point of the table.
"""
import uuid
from datetime import datetime, timezone as tz
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.modules.execution.models import ChangeLog, SuggestionAction

# Constrained by ck_suggestion_actions_action in the database.
ACTION_CREATED = "created"
ACTION_APPROVED = "approved"
ACTION_REJECTED = "rejected"
ACTION_DEFERRED = "deferred"
ACTION_EXECUTED = "executed"
ACTION_EXECUTION_FAILED = "execution_failed"
ACTION_EXPIRED = "expired"
ACTION_ROLLED_BACK = "rolled_back"

# Constrained by ck_change_log_source.
SOURCE_SUGGESTION_EXECUTION = "suggestion_execution"
SOURCE_MANUAL_EDIT = "manual_edit"
SOURCE_ROLLBACK = "rollback"

# Constrained by ck_change_log_entity_type.
ENTITY_CAMPAIGN = "campaign"
ENTITY_AD_GROUP = "ad_group"
ENTITY_TARGET = "target"


class ExecutionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── suggestion_actions (append-only) ──────────────────────────────────

    def record_attempt(
        self,
        suggestion_id: uuid.UUID,
        action: str,
        performed_by: Optional[uuid.UUID] = None,
        request: Optional[dict[str, Any]] = None,
        response: Optional[dict[str, Any]] = None,
        status_code: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> SuggestionAction:
        """Append one attempt record. Never updates an existing row."""
        row = SuggestionAction(
            suggestion_id=suggestion_id,
            action=action,
            performed_by=performed_by,
            amazon_api_request=request,
            amazon_api_response=response,
            amazon_api_status_code=status_code,
            notes=notes,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def actions_for(self, suggestion_id: uuid.UUID) -> list[SuggestionAction]:
        return (
            self.db.query(SuggestionAction)
            .filter(SuggestionAction.suggestion_id == suggestion_id)
            .order_by(SuggestionAction.created_at.desc())
            .all()
        )

    # ── change_log ────────────────────────────────────────────────────────

    def record_change(
        self,
        profile_id: uuid.UUID,
        entity_type: str,
        field_changed: str,
        old_value: Optional[str],
        new_value: Optional[str],
        source: str,
        entity_id: Optional[uuid.UUID] = None,
        amazon_entity_id: Optional[int] = None,
        suggestion_id: Optional[uuid.UUID] = None,
        changed_by: Optional[uuid.UUID] = None,
    ) -> ChangeLog:
        """Record that something really changed on Amazon.

        Only call this after a confirmed successful write. A row here is read
        as evidence the change happened, and is what rollback restores from.
        """
        row = ChangeLog(
            profile_id=profile_id,
            entity_type=entity_type,
            entity_id=entity_id,
            amazon_entity_id=amazon_entity_id,
            field_changed=field_changed,
            old_value=None if old_value is None else str(old_value),
            new_value=None if new_value is None else str(new_value),
            suggestion_id=suggestion_id,
            changed_by=changed_by,
            source=source,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_change(self, change_id: uuid.UUID) -> Optional[ChangeLog]:
        return self.db.query(ChangeLog).filter(ChangeLog.id == change_id).one_or_none()

    def mark_rolled_back(self, change_id: uuid.UUID) -> Optional[ChangeLog]:
        """Stamp the original row. History is never rewritten — the rollback
        itself is recorded as a separate change_log entry."""
        row = self.get_change(change_id)
        if row is None:
            return None
        row.rolled_back_at = datetime.now(tz.utc)
        self.db.commit()
        self.db.refresh(row)
        return row

    def latest_change_for_suggestion(self, suggestion_id: uuid.UUID) -> Optional[ChangeLog]:
        return (
            self.db.query(ChangeLog)
            .filter(ChangeLog.suggestion_id == suggestion_id)
            .order_by(ChangeLog.changed_at.desc())
            .first()
        )
