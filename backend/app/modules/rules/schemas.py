"""Pydantic schemas for Rules Engine (Sprint 3)."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


# ── Configuration sub-schemas ──────────────────────────────────────────────────

class RuleCondition(BaseModel):
    """One condition in a rule: field op value (e.g. acos > 30)."""
    # clicks | orders | cost | sales | acos | roas | ctr | conversion_rate | impressions
    field:    str
    # gt | gte | lt | lte | eq | neq
    operator: str
    # user-facing units: % fields use 30 for 30%, dollar fields use raw dollars
    value:    float


class BidAction(BaseModel):
    """Action for bid-type rules (increase/decrease bid by %)."""
    type:    str    # increase_bid | decrease_bid
    percent: float  # 1–100


# ── Rule CRUD schemas ──────────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    profile_id:         uuid.UUID
    name:               str
    description:        Optional[str]         = None
    rule_type:          str                   # negative | harvest | bid | budget | placement
    status:             str                   = "enabled"
    configuration_json: dict[str, Any]

# Scoping. Empty lists mean "everything in the marketplace", which is how every
# rule behaved before scoping was reachable. rule_campaign_scope has existed
# since P4-4 and the engine always filtered on it, but no endpoint accepted
# campaign_ids — so the table could never be populated and the feature was dead
# from end to end while looking implemented.
    campaign_ids:       list[uuid.UUID]       = Field(default_factory=list)
    ad_group_ids:       list[uuid.UUID]       = Field(default_factory=list)


class RuleUpdate(BaseModel):
    name:               Optional[str]         = None
    description:        Optional[str]         = None
    rule_type:          Optional[str]         = None
    status:             Optional[str]         = None
    configuration_json: Optional[dict[str, Any]] = None
    # None means "leave the scope as it is"; [] means "clear it". A single
    # optional list cannot express both, and silently widening a rule to the
    # whole marketplace on an unrelated edit would be the worse default.
    campaign_ids:       Optional[list[uuid.UUID]] = None
    ad_group_ids:       Optional[list[uuid.UUID]] = None


class RuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:                 uuid.UUID
    profile_id:         uuid.UUID
    name:               str
    description:        Optional[str]         = None
    rule_type:          str
    status:             str
    configuration_json: dict[str, Any]
    created_by:         Optional[uuid.UUID]   = None
    created_at:         datetime
    updated_at:         datetime
    deleted_at:         Optional[datetime]    = None
    # Populated by the router from the scope tables, so a rule always reports
    # what it is actually limited to rather than leaving the UI to guess.
    campaign_ids:       list[uuid.UUID]       = Field(default_factory=list)
    ad_group_ids:       list[uuid.UUID]       = Field(default_factory=list)


# ── Execution schemas ──────────────────────────────────────────────────────────

class RuleExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:                   uuid.UUID
    rule_id:              uuid.UUID
    profile_id:           uuid.UUID
    started_at:           datetime
    completed_at:         Optional[datetime]  = None
    execution_status:     str
    rows_evaluated:       int
    suggestions_generated: int
    error_message:        Optional[str]       = None
    created_at:           datetime


class ExecuteRuleResponse(BaseModel):
    rule_id:               str
    rule_name:             str
    execution_id:          str
    rows_evaluated:        int
    suggestions_generated: int
    execution_status:      str
    duration_ms:           int


# ── Rule templates ─────────────────────────────────────────────────────────────

class RuleTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:                 uuid.UUID
    name:               str
    description:        Optional[str]
    rule_type:          str
    configuration_json: dict
    is_builtin:         bool
    created_at:         datetime


class RuleTemplateCreate(BaseModel):
    name:        str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    # Matches ck_rule_templates_rule_type in migration 016. A value outside
    # this set raises CheckViolation on insert.
    rule_type:   Literal["negative", "harvest", "bid", "budget"]
    configuration_json: dict
