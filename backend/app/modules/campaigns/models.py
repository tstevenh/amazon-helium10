"""
SQLAlchemy ORM models for campaigns, ad_groups, and targets.

These models map to the tables created in migration 003 and amended by migration 007.
  - deleted_at   added by 007 (soft delete)
  - targets.expression_text widened to Text() by 007
"""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, Date, DateTime,
    ForeignKey, Numeric, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    __table_args__ = (
        CheckConstraint("ad_product IN ('SP', 'SB', 'SD')", name="ck_campaigns_ad_product"),
        CheckConstraint("status IN ('enabled', 'paused', 'archived')", name="ck_campaigns_status"),
        CheckConstraint(
            "targeting_type IS NULL OR targeting_type IN ('manual', 'auto')",
            name="ck_campaigns_targeting_type",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    profile_id = Column(UUID(as_uuid=True), ForeignKey("ads_profiles.id", ondelete="CASCADE"), nullable=False)
    amazon_campaign_id = Column(BigInteger(), nullable=False, unique=True)
    ad_product = Column(String(5), nullable=False, server_default="SP")
    name = Column(String(500), nullable=False)
    status = Column(String(20), nullable=False)
    targeting_type = Column(String(10), nullable=True)
    daily_budget = Column(Numeric(12, 2), nullable=True)
    start_date = Column(Date(), nullable=True)
    end_date = Column(Date(), nullable=True)
    bidding_strategy = Column(String(50), nullable=True)
    raw_payload = Column(JSONB(), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # migration 007
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    ad_groups = relationship("AdGroup", back_populates="campaign", cascade="all, delete-orphan")


class AdGroup(Base):
    __tablename__ = "ad_groups"

    __table_args__ = (
        CheckConstraint("status IN ('enabled', 'paused', 'archived')", name="ck_ad_groups_status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    amazon_ad_group_id = Column(BigInteger(), nullable=False, unique=True)
    name = Column(String(500), nullable=False)
    default_bid = Column(Numeric(8, 2), nullable=True)
    status = Column(String(20), nullable=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # migration 007
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    campaign = relationship("Campaign", back_populates="ad_groups")
    targets = relationship("Target", back_populates="ad_group", cascade="all, delete-orphan")


class Target(Base):
    __tablename__ = "targets"

    __table_args__ = (
        CheckConstraint("target_kind IN ('keyword', 'product', 'audience')", name="ck_targets_target_kind"),
        CheckConstraint(
            "match_type IS NULL OR match_type IN ('exact', 'phrase', 'broad', 'auto')",
            name="ck_targets_match_type",
        ),
        CheckConstraint("status IN ('enabled', 'paused', 'archived')", name="ck_targets_status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    ad_group_id = Column(UUID(as_uuid=True), ForeignKey("ad_groups.id", ondelete="CASCADE"), nullable=False)
    amazon_target_id = Column(BigInteger(), nullable=False, unique=True)
    target_kind = Column(String(10), nullable=False)
    match_type = Column(String(20), nullable=True)
    expression_text = Column(Text(), nullable=True)  # widened to Text in migration 007
    bid = Column(Numeric(8, 2), nullable=True)
    status = Column(String(20), nullable=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # migration 007
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    ad_group = relationship("AdGroup", back_populates="targets")
