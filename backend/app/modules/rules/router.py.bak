"""Rules Engine router (Sprint 3).

Routes:
  GET    /rules                     — list rules for a profile
  POST   /rules                     — create rule
  GET    /rules/{id}                — get single rule
  PUT    /rules/{id}                — update rule
  DELETE /rules/{id}                — soft delete rule
  POST   /rules/{id}/clone          — clone rule (starts disabled)
  POST   /rules/{id}/enable         — enable rule
  POST   /rules/{id}/disable        — disable rule
  POST   /rules/{id}/execute        — run rule now, create suggestions
  GET    /rules/{id}/executions     — execution history
"""
from __future__ import annotations
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.audit_log.repository import AuditLogRepository
from app.modules.rules.repository import RuleRepository, RuleExecutionRepository
from app.modules.rules.schemas import (
    RuleCreate,
    RuleUpdate,
    RuleResponse,
    RuleExecutionResponse,
    ExecuteRuleResponse,
)
from app.modules.rules.service import RuleEngine

rules_router = APIRouter(prefix="/rules", tags=["rules"])


def _audit(
    db: Session,
    user_id: uuid.UUID,
    entity_id: uuid.UUID,
    action: str,
    extra: Optional[dict] = None,
) -> None:
    AuditLogRepository(db).create(
        user_id     = user_id,
        entity_type = "rule",
        entity_id   = entity_id,
        action      = action,
        extra_data  = extra or {},
    )


# ── List ───────────────────────────────────────────────────────────────────────

@rules_router.get("", response_model=list[RuleResponse])
def list_rules(
    profile_id:       uuid.UUID = Query(...),
    include_disabled: bool      = Query(True),
    db:       Session = Depends(get_db),
    _user:    User    = Depends(get_current_user),
) -> list[RuleResponse]:
    return RuleRepository(db).get_all(profile_id, include_disabled=include_disabled)


# ── Create ─────────────────────────────────────────────────────────────────────

@rules_router.post("", response_model=RuleResponse, status_code=201)
def create_rule(
    body:  RuleCreate,
    db:    Session = Depends(get_db),
    _user: User    = Depends(get_current_user),
) -> RuleResponse:
    rule = RuleRepository(db).create(dict(
        profile_id         = body.profile_id,
        name               = body.name,
        description        = body.description,
        rule_type          = body.rule_type,
        status             = body.status,
        configuration_json = body.configuration_json,
        created_by         = _user.id,
    ))
    db.commit()
    _audit(db, _user.id, rule.id, "rule_created", {"name": rule.name, "rule_type": rule.rule_type})
    db.commit()
    return rule


# ── Get ────────────────────────────────────────────────────────────────────────

@rules_router.get("/{rule_id}", response_model=RuleResponse)
def get_rule(
    rule_id: uuid.UUID,
    db:      Session = Depends(get_db),
    _user:   User    = Depends(get_current_user),
) -> RuleResponse:
    rule = RuleRepository(db).get_by_id(rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    return rule


# ── Update ─────────────────────────────────────────────────────────────────────

@rules_router.put("/{rule_id}", response_model=RuleResponse)
def update_rule(
    rule_id: uuid.UUID,
    body:    RuleUpdate,
    db:      Session = Depends(get_db),
    _user:   User    = Depends(get_current_user),
) -> RuleResponse:
    repo = RuleRepository(db)
    rule = repo.get_by_id(rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    rule = repo.update(rule, updates)
    db.commit()
    _audit(db, _user.id, rule.id, "rule_updated", {"fields": list(updates.keys())})
    db.commit()
    return rule


# ── Delete (soft) ──────────────────────────────────────────────────────────────

@rules_router.delete("/{rule_id}", status_code=204, response_model=None)
def delete_rule(
    rule_id: uuid.UUID,
    db:      Session = Depends(get_db),
    _user:   User    = Depends(get_current_user),
):
    repo = RuleRepository(db)
    rule = repo.get_by_id(rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    repo.soft_delete(rule)
    db.commit()
    _audit(db, _user.id, rule_id, "rule_deleted", {})
    db.commit()


# ── Clone ──────────────────────────────────────────────────────────────────────

@rules_router.post("/{rule_id}/clone", response_model=RuleResponse, status_code=201)
def clone_rule(
    rule_id: uuid.UUID,
    db:      Session = Depends(get_db),
    _user:   User    = Depends(get_current_user),
) -> RuleResponse:
    repo = RuleRepository(db)
    rule = repo.get_by_id(rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    cloned = repo.clone(rule, f"Copy of {rule.name}", _user.id)
    db.commit()
    _audit(db, _user.id, cloned.id, "rule_cloned", {
        "source_rule_id": str(rule_id),
        "name": cloned.name,
    })
    db.commit()
    return cloned


# ── Enable / Disable ───────────────────────────────────────────────────────────

@rules_router.post("/{rule_id}/enable", response_model=RuleResponse)
def enable_rule(
    rule_id: uuid.UUID,
    db:      Session = Depends(get_db),
    _user:   User    = Depends(get_current_user),
) -> RuleResponse:
    repo = RuleRepository(db)
    rule = repo.get_by_id(rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    rule = repo.update(rule, {"status": "enabled"})
    db.commit()
    _audit(db, _user.id, rule_id, "rule_enabled", {})
    db.commit()
    return rule


@rules_router.post("/{rule_id}/disable", response_model=RuleResponse)
def disable_rule(
    rule_id: uuid.UUID,
    db:      Session = Depends(get_db),
    _user:   User    = Depends(get_current_user),
) -> RuleResponse:
    repo = RuleRepository(db)
    rule = repo.get_by_id(rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    rule = repo.update(rule, {"status": "disabled"})
    db.commit()
    _audit(db, _user.id, rule_id, "rule_disabled", {})
    db.commit()
    return rule


# ── Execute ────────────────────────────────────────────────────────────────────

@rules_router.post("/{rule_id}/execute", response_model=ExecuteRuleResponse)
def execute_rule(
    rule_id: uuid.UUID,
    db:      Session = Depends(get_db),
    _user:   User    = Depends(get_current_user),
) -> ExecuteRuleResponse:
    """
    Run the rule now against its profile's search terms.
    Creates Suggestions only — never modifies Amazon Ads.
    Human approval of each suggestion remains mandatory.
    """
    rule = RuleRepository(db).get_by_id(rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    if rule.status != "enabled":
        raise HTTPException(400, "Cannot execute a disabled rule — enable it first")

    try:
        result = RuleEngine(db).execute(rule, _user.id)
        db.commit()
        _audit(db, _user.id, rule_id, "rule_executed", {
            "rows_evaluated":        result["rows_evaluated"],
            "suggestions_generated": result["suggestions_generated"],
        })
        db.commit()
        return result
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"Rule execution failed: {exc}") from exc


# ── Execution history ──────────────────────────────────────────────────────────

@rules_router.get("/{rule_id}/executions", response_model=list[RuleExecutionResponse])
def get_rule_executions(
    rule_id: uuid.UUID,
    limit:   int     = Query(10, ge=1, le=100),
    db:      Session = Depends(get_db),
    _user:   User    = Depends(get_current_user),
) -> list[RuleExecutionResponse]:
    rule = RuleRepository(db).get_by_id(rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    return RuleExecutionRepository(db).get_by_rule(rule_id, limit=limit)
