"""Pydantic schemas for suggestions (Sprint 2.5 + Sprint 3)."""
from __future__ import annotations
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict


class SuggestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:               uuid.UUID
    profile_id:       uuid.UUID
    campaign_id:      Optional[uuid.UUID] = None
    ad_group_id:      Optional[uuid.UUID] = None
    search_term:      str
    suggestion_type:  str
    kind:             str
    reason:           str
    metrics_snapshot: dict[str, Any]
    status:           str
    resolved_by:      Optional[uuid.UUID] = None
    resolved_at:      Optional[datetime]  = None
    created_at:       datetime
    updated_at:       datetime

    # Sprint 2.5
    confidence_score: int            = 0
    campaign_count:   int            = 1
    ad_group_count:   int            = 1
    total_spend:      Decimal        = Decimal("0")
    total_sales:      Decimal        = Decimal("0")
    total_orders:     int            = 0

    # Sprint 3 — source tracking
    source_type:      str            = "engine"
    source_rule_id:   Optional[uuid.UUID] = None
    source_rule_name: Optional[str]  = None


class ResolveRequest(BaseModel):
    reason: Optional[str] = None


class BulkResolveRequest(BaseModel):
    ids:    list[uuid.UUID]
    reason: Optional[str] = None


class BulkResolveResponse(BaseModel):
    resolved: int
    skipped:  int   # already approved / rejected


class GenerateResponse(BaseModel):
    profile_id:            str
    suggestions_generated: int
