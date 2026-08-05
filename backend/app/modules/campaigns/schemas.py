"""Pydantic schemas for campaigns, ad groups, and targets (Sprint 1C)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ── Campaigns ─────────────────────────────────────────────────────────────

class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    profile_id: uuid.UUID
    amazon_campaign_id: int
    ad_product: str
    name: str
    status: str
    targeting_type: Optional[str] = None
    daily_budget: Optional[Decimal] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    bidding_strategy: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# ── Ad Groups ─────────────────────────────────────────────────────────────

class AdGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    amazon_ad_group_id: int
    name: str
    default_bid: Optional[Decimal] = None
    status: str
    last_synced_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# ── Targets ───────────────────────────────────────────────────────────────

class TargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ad_group_id: uuid.UUID
    amazon_target_id: int
    target_kind: str
    match_type: Optional[str] = None
    expression_text: Optional[str] = None
    bid: Optional[Decimal] = None
    status: str
    last_synced_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# ── Sync responses ────────────────────────────────────────────────────────

class SyncResult(BaseModel):
    upserted: int
    soft_deleted: int
    partial: bool = False
    warnings: list[str] = []
    pages_fetched: int = 0
    rows_fetched: int = 0


class CampaignSyncResponse(BaseModel):
    message: str
    seller_account_id: uuid.UUID
    campaigns: SyncResult


class AdGroupSyncResponse(BaseModel):
    message: str
    seller_account_id: uuid.UUID
    ad_groups: SyncResult


class TargetSyncResponse(BaseModel):
    message: str
    seller_account_id: uuid.UUID
    targets: SyncResult


class SyncAllResponse(BaseModel):
    message: str
    seller_account_id: uuid.UUID
    campaigns: SyncResult
    ad_groups: SyncResult
    targets: SyncResult
