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
from sqlalchemy import func

from app.modules.campaigns.models import AdGroup, Campaign
from app.modules.rules.models import (
    RuleAdGroupScope, RuleCampaignScope, RuleTemplate,
)
from app.modules.rules.repository import RuleRepository, RuleExecutionRepository
from app.modules.rules.schemas import (
    RuleTemplateCreate,
    RuleTemplateResponse,
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
    rules = RuleRepository(db).get_all(profile_id, include_disabled=include_disabled)
    return [_with_scope(db, r) for r in rules]



# ── Scoping ────────────────────────────────────────────────────────────────────
# Empty scope means "the whole marketplace", which is how every rule behaved
# before this was reachable. rule_campaign_scope shipped in P4-4 and the engine
# always honoured it, but nothing could write to it, so the feature was dead end
# to end while appearing implemented.

_CAMPAIGN_LEVEL_TYPES = ("budget", "placement")


def _validate_scope(
    db: Session, rule_type: str, profile_id: uuid.UUID,
    campaign_ids: list[uuid.UUID], ad_group_ids: list[uuid.UUID],
) -> None:
    """Reject a scope the engine could not honour, rather than storing it.

    An ad-group scope on a budget rule is the important case: an Amazon budget
    belongs to a campaign, so the engine reads campaign totals and never looks
    at ad groups. Accepting it would give the operator a rule that quietly
    ignored half of what they configured.
    """
    if ad_group_ids and rule_type in _CAMPAIGN_LEVEL_TYPES:
        raise HTTPException(
            400,
            f"{rule_type} rules act on whole campaigns, so they cannot be scoped "
            f"to ad groups. Amazon holds the budget and the placement adjustments "
            f"on the campaign, not the ad group. Scope by campaign instead.",
        )

    if campaign_ids:
        found = db.query(Campaign).filter(
            Campaign.id.in_(campaign_ids), Campaign.deleted_at.is_(None),
        ).all()
        by_id = {c.id: c for c in found}
        for cid in campaign_ids:
            c = by_id.get(cid)
            if c is None:
                raise HTTPException(400, f"Campaign {cid} not found")
            if c.profile_id != profile_id:
                raise HTTPException(
                    400,
                    f"Campaign '{c.name}' belongs to a different marketplace than "
                    f"this rule",
                )

    if ad_group_ids:
        rows = (
            db.query(AdGroup, Campaign)
            .join(Campaign, Campaign.id == AdGroup.campaign_id)
            .filter(AdGroup.id.in_(ad_group_ids), AdGroup.deleted_at.is_(None))
            .all()
        )
        by_id = {ag.id: (ag, c) for ag, c in rows}
        for gid in ad_group_ids:
            pair = by_id.get(gid)
            if pair is None:
                raise HTTPException(400, f"Ad group {gid} not found")
            ag, camp = pair
            if camp.profile_id != profile_id:
                raise HTTPException(
                    400,
                    f"Ad group '{ag.name}' belongs to a different marketplace than "
                    f"this rule",
                )
            # An ad group outside the campaign scope would match nothing, and the
            # rule would look broken rather than misconfigured.
            if campaign_ids and camp.id not in set(campaign_ids):
                raise HTTPException(
                    400,
                    f"Ad group '{ag.name}' is in campaign '{camp.name}', which is "
                    f"not in this rule's campaign scope. Add that campaign, or "
                    f"remove the ad group.",
                )


def _replace_scope(
    db: Session, rule_id: uuid.UUID,
    campaign_ids: Optional[list[uuid.UUID]], ad_group_ids: Optional[list[uuid.UUID]],
) -> None:
    """None leaves a scope untouched; [] clears it."""
    if campaign_ids is not None:
        db.query(RuleCampaignScope).filter(RuleCampaignScope.rule_id == rule_id).delete()
        for cid in dict.fromkeys(campaign_ids):     # de-dupe, keep order
            db.add(RuleCampaignScope(rule_id=rule_id, campaign_id=cid))
    if ad_group_ids is not None:
        db.query(RuleAdGroupScope).filter(RuleAdGroupScope.rule_id == rule_id).delete()
        for gid in dict.fromkeys(ad_group_ids):
            db.add(RuleAdGroupScope(rule_id=rule_id, ad_group_id=gid))


def _with_scope(db: Session, rule) -> RuleResponse:
    """A rule always reports what it is limited to, so the UI need not guess."""
    out = RuleResponse.model_validate(rule)
    out.campaign_ids = [
        r.campaign_id for r in db.query(RuleCampaignScope)
        .filter(RuleCampaignScope.rule_id == rule.id).all()
    ]
    out.ad_group_ids = [
        r.ad_group_id for r in db.query(RuleAdGroupScope)
        .filter(RuleAdGroupScope.rule_id == rule.id).all()
    ]
    return out

# ── Create ─────────────────────────────────────────────────────────────────────

@rules_router.post("", response_model=RuleResponse, status_code=201)
def create_rule(
    body:  RuleCreate,
    db:    Session = Depends(get_db),
    _user: User    = Depends(get_current_user),
) -> RuleResponse:
    _validate_scope(db, body.rule_type, body.profile_id,
                    body.campaign_ids, body.ad_group_ids)
    rule = RuleRepository(db).create(dict(
        profile_id         = body.profile_id,
        name               = body.name,
        description        = body.description,
        rule_type          = body.rule_type,
        status             = body.status,
        configuration_json = body.configuration_json,
        created_by         = _user.id,
    ))
    _replace_scope(db, rule.id, body.campaign_ids, body.ad_group_ids)
    db.commit()
    _audit(db, _user.id, rule.id, "rule_created", {
        "name": rule.name, "rule_type": rule.rule_type,
        "campaigns": len(body.campaign_ids), "ad_groups": len(body.ad_group_ids),
    })
    db.commit()
    return _with_scope(db, rule)


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
    return _with_scope(db, rule)


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

    # Scope is stored in its own tables, so it must not be passed to the rule
    # row update — SQLAlchemy would raise on an unknown attribute.
    payload = body.model_dump()
    campaign_ids = payload.pop("campaign_ids", None)
    ad_group_ids = payload.pop("ad_group_ids", None)
    updates = {k: v for k, v in payload.items() if v is not None}
    _validate_scope(
        db, updates.get("rule_type", rule.rule_type), rule.profile_id,
        campaign_ids or [], ad_group_ids or [],
    )
    rule = repo.update(rule, updates)
    _replace_scope(db, rule.id, campaign_ids, ad_group_ids)
    db.commit()
    _audit(db, _user.id, rule.id, "rule_updated", {"fields": list(updates.keys())})
    db.commit()
    # _with_scope, not the bare ORM object: RuleResponse defaults campaign_ids to
    # [] and the Rule row has no such attribute, so returning `rule` reported an
    # empty scope on every update while the tables were untouched. A UI trusting
    # that response would show the scope as cleared and could save it back —
    # turning a display bug into real data loss.
    return _with_scope(db, rule)


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
    db.flush()
    # Carry the scope across. Without this, cloning a rule limited to one
    # campaign produced a rule that ran over the entire marketplace — silently,
    # and the clone starts disabled so nobody would notice until they enabled it.
    src_campaigns = [
        r.campaign_id for r in db.query(RuleCampaignScope)
        .filter(RuleCampaignScope.rule_id == rule.id).all()
    ]
    src_ad_groups = [
        r.ad_group_id for r in db.query(RuleAdGroupScope)
        .filter(RuleAdGroupScope.rule_id == rule.id).all()
    ]
    _replace_scope(db, cloned.id, src_campaigns, src_ad_groups)
    db.commit()
    _audit(db, _user.id, cloned.id, "rule_cloned", {
        "source_rule_id": str(rule_id),
        "name": cloned.name,
        "campaigns": len(src_campaigns),
        "ad_groups": len(src_ad_groups),
    })
    db.commit()
    return _with_scope(db, cloned)


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
    return _with_scope(db, rule)


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
    return _with_scope(db, rule)


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


# ── Rule templates ─────────────────────────────────────────────────────────────
#
# Spec Part 21.2: /rule-templates (GET/POST). Separate router because these are
# reference data, not scoped to a profile — a template is a shape, and only
# becomes marketplace-specific when a rule is created from it.

templates_router = APIRouter(prefix="/rule-templates", tags=["rule-templates"])


@templates_router.get("", response_model=list[RuleTemplateResponse])
def list_rule_templates(
    rule_type: Optional[str] = Query(None),
    db:        Session       = Depends(get_db),
    _user:     User          = Depends(get_current_user),
) -> list[RuleTemplate]:
    q = db.query(RuleTemplate).filter(RuleTemplate.deleted_at.is_(None))
    if rule_type:
        q = q.filter(RuleTemplate.rule_type == rule_type)
    # Built-ins first: a new operator wants the vetted starting points before
    # whatever a colleague saved last week.
    return q.order_by(RuleTemplate.is_builtin.desc(), RuleTemplate.name.asc()).all()


@templates_router.post("", response_model=RuleTemplateResponse, status_code=201)
def create_rule_template(
    body:  RuleTemplateCreate,
    db:    Session = Depends(get_db),
    _user: User    = Depends(get_current_user),
) -> RuleTemplate:
    template = RuleTemplate(
        name               = body.name,
        description        = body.description,
        rule_type          = body.rule_type,
        configuration_json = body.configuration_json,
        is_builtin         = False,   # only the seeder creates built-ins
        created_by         = _user.id,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@templates_router.delete("/{template_id}", status_code=204)
def delete_rule_template(
    template_id: uuid.UUID,
    db:          Session = Depends(get_db),
    _user:       User    = Depends(get_current_user),
):
    # No return annotation on purpose. This module uses
    # `from __future__ import annotations`, so `-> None` reaches FastAPI as the
    # string "None", which it reads as a response model and then rejects
    # against 204 ("Status code 204 must not have a response body").
    template = (
        db.query(RuleTemplate)
        .filter(RuleTemplate.id == template_id, RuleTemplate.deleted_at.is_(None))
        .first()
    )
    if template is None:
        raise HTTPException(404, "Template not found")
    if template.is_builtin:
        raise HTTPException(
            400,
            "Built-in templates cannot be deleted. Create your own template "
            "instead, or ignore this one.",
        )
    template.deleted_at = func.now()
    db.commit()
