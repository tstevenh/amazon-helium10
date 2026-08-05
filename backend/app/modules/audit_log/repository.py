"""Repository for audit_log (Sprint 2)."""
from __future__ import annotations
import uuid
from typing import Any, Optional
from sqlalchemy.orm import Session
from app.modules.audit_log.models import AuditLog


class AuditLogRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        user_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        reason: Optional[str] = None,
        extra_data: Optional[dict] = None,
    ) -> AuditLog:
        entry = AuditLog(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            reason=reason,
            extra_data=extra_data,
        )
        self.db.add(entry)
        self.db.flush()
        return entry
