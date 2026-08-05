"""Pydantic schemas for Rules Engine (Sprint 3)."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict


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
    rule_type:          str                   # negative | harvest | bid
    status:             str                   = "enabled"
    configuration_json: dict[str, Any]


class RuleUpdate(BaseModel):
    name:               Optional[str]         = None
    description:        Optional[str]         = None
    rule_type:          Optional[str]         = None
    status:             Optional[str]         = None
    configuration_json: Optional[dict[str, Any]] = None


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
