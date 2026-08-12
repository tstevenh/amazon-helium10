"""Pydantic schemas for performance endpoints (Sprint 4B)."""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


# ── Per-row response shapes ────────────────────────────────────────────────

class CampaignPerfRow(BaseModel):
    date: date
    impressions: int
    clicks: int
    spend: Decimal
    sales: Decimal
    orders: int
    ctr: Optional[Decimal] = None
    cpc: Optional[Decimal] = None
    acos: Optional[Decimal] = None
    roas: Optional[Decimal] = None

    model_config = {"from_attributes": True}


class AdGroupPerfRow(BaseModel):
    date: date
    impressions: int
    clicks: int
    spend: Decimal
    sales: Decimal
    orders: int
    ctr: Optional[Decimal] = None
    cpc: Optional[Decimal] = None
    acos: Optional[Decimal] = None
    roas: Optional[Decimal] = None

    model_config = {"from_attributes": True}


# ── Aggregated summary (for cards / campaign manager columns) ──────────────

class PerfSummary(BaseModel):
    """Aggregate of a date range — one row per campaign or ad group."""
    impressions: int = 0
    clicks: int = 0
    spend: Decimal = Decimal("0")
    sales: Decimal = Decimal("0")
    orders: int = 0
    ctr: Optional[Decimal] = None    # clicks / impressions
    cpc: Optional[Decimal] = None    # spend / clicks
    acos: Optional[Decimal] = None   # spend / sales * 100
    roas: Optional[Decimal] = None   # sales / spend


# ── Campaign manager list row — campaign + aggregated metrics ──────────────

class CampaignWithMetrics(BaseModel):
    id: uuid.UUID
    profile_id: uuid.UUID
    name: str
    ad_product: str
    status: str
    daily_budget: Optional[Decimal] = None
    targeting_type: Optional[str] = None
    # metrics (None when no performance data in range)
    impressions: Optional[int] = None
    clicks: Optional[int] = None
    spend: Optional[Decimal] = None
    sales: Optional[Decimal] = None
    orders: Optional[int] = None
    ctr: Optional[Decimal] = None
    cpc: Optional[Decimal] = None
    acos: Optional[Decimal] = None
    roas: Optional[Decimal] = None


# ── Sync response ──────────────────────────────────────────────────────────

class PerfSyncResult(BaseModel):
    campaign_rows: int = 0
    ad_group_rows: int = 0
    target_rows: int = 0
    placement_rows: int = 0
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    profiles_synced: int = 0


class PerfSyncResponse(BaseModel):
    message: str
    result: PerfSyncResult
