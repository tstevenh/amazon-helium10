"""Repository for Rules Engine (Sprint 3)."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.rules.models import Rule, RuleExecution


class RuleRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_all(
        self,
        profile_id: uuid.UUID,
        include_disabled: bool = True,
    ) -> list[Rule]:
        q = self.db.query(Rule).filter(
            Rule.profile_id == profile_id,
            Rule.deleted_at.is_(None),
        )
        if not include_disabled:
            q = q.filter(Rule.status == "enabled")
        return q.order_by(Rule.created_at.desc()).all()

    def get_by_id(self, rule_id: uuid.UUID) -> Optional[Rule]:
        return self.db.query(Rule).filter(
            Rule.id == rule_id,
            Rule.deleted_at.is_(None),
        ).first()

    def create(self, data: dict) -> Rule:
        rule = Rule(**data)
        self.db.add(rule)
        self.db.flush()
        return rule

    def update(self, rule: Rule, data: dict) -> Rule:
        for k, v in data.items():
            setattr(rule, k, v)
        rule.updated_at = datetime.utcnow()
        self.db.flush()
        return rule

    def soft_delete(self, rule: Rule) -> Rule:
        rule.deleted_at = datetime.utcnow()
        rule.updated_at = datetime.utcnow()
        self.db.flush()
        return rule

    def clone(self, rule: Rule, new_name: str, created_by: uuid.UUID) -> Rule:
        """Create a copy of rule with status=disabled. Clones start inactive."""
        return self.create(dict(
            profile_id         = rule.profile_id,
            name               = new_name,
            description        = rule.description,
            rule_type          = rule.rule_type,
            status             = "disabled",
            configuration_json = rule.configuration_json,
            created_by         = created_by,
        ))


class RuleExecutionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, rule_id: uuid.UUID, profile_id: uuid.UUID) -> RuleExecution:
        rec = RuleExecution(rule_id=rule_id, profile_id=profile_id)
        self.db.add(rec)
        self.db.flush()
        return rec

    def complete(
        self,
        execution_id: uuid.UUID,
        rows_evaluated: int,
        suggestions_generated: int,
    ) -> RuleExecution:
        rec = self.db.query(RuleExecution).filter(RuleExecution.id == execution_id).first()
        if rec:
            rec.completed_at          = datetime.utcnow()
            rec.execution_status      = "completed"
            rec.rows_evaluated        = rows_evaluated
            rec.suggestions_generated = suggestions_generated
            self.db.flush()
        return rec

    def fail(self, execution_id: uuid.UUID, error_message: str) -> RuleExecution:
        rec = self.db.query(RuleExecution).filter(RuleExecution.id == execution_id).first()
        if rec:
            rec.completed_at     = datetime.utcnow()
            rec.execution_status = "failed"
            rec.error_message    = error_message
            self.db.flush()
        return rec

    def get_by_rule(self, rule_id: uuid.UUID, limit: int = 10) -> list[RuleExecution]:
        return (
            self.db.query(RuleExecution)
            .filter(RuleExecution.rule_id == rule_id)
            .order_by(RuleExecution.started_at.desc())
            .limit(limit)
            .all()
        )

    def get_by_profile(self, profile_id: uuid.UUID, limit: int = 50) -> list[RuleExecution]:
        return (
            self.db.query(RuleExecution)
            .filter(RuleExecution.profile_id == profile_id)
            .order_by(RuleExecution.started_at.desc())
            .limit(limit)
            .all()
        )
