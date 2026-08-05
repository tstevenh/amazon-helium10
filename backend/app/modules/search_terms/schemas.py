"""Pydantic schemas for search_terms (Sprint 2)."""
from __future__ import annotations
import uuid
from decimal import Decimal
from typing import Optional
from datetime import date
from pydantic import BaseModel, ConfigDict


class SearchTermRow(BaseModel):
    """Aggregated row returned by GET /search-terms."""
    model_config = ConfigDict(from_attributes=True)

    search_term: str
    campaign_id: Optional[uuid.UUID] = None
    campaign_name: Optional[str] = None
    ad_group_id: Optional[uuid.UUID] = None
    ad_group_name: Optional[str] = None
    impressions: int
    clicks: int
    cost: Decimal
    sales: Decimal
    orders: int
    units: int
    ctr: Decimal
    cpc: Decimal
    acos: Optional[Decimal] = None
    roas: Optional[Decimal] = None
    conversion_rate: Decimal


class SearchTermSyncResponse(BaseModel):
    message: str
    account_id: str
    terms_synced: int
    suggestions_generated: int
    # Per-profile failures. Empty on full success. A non-empty list means the
    # sync is partial — terms_synced is not the whole picture.
    errors: list[str] = []
