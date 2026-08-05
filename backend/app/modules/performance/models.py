"""SQLAlchemy ORM models for daily performance tables (Sprint 4B)."""
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Integer, Numeric, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class CampaignPerformanceDaily(Base):
    """campaign_performance_daily — created in migration 004."""
    __tablename__ = "campaign_performance_daily"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date(), nullable=False)
    impressions = Column(BigInteger(), nullable=False, server_default="0")
    clicks = Column(BigInteger(), nullable=False, server_default="0")
    spend = Column(Numeric(12, 2), nullable=False, server_default="0")
    sales = Column(Numeric(12, 2), nullable=False, server_default="0")
    orders = Column(Integer(), nullable=False, server_default="0")
    ctr = Column(Numeric(6, 4), nullable=True)
    cpc = Column(Numeric(8, 4), nullable=True)
    acos = Column(Numeric(6, 2), nullable=True)
    roas = Column(Numeric(6, 2), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("campaign_id", "date", name="uq_cpd_campaign_date"),
    )


class AdGroupPerformanceDaily(Base):
    """ad_group_performance_daily — created in migration 011."""
    __tablename__ = "ad_group_performance_daily"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ad_group_id = Column(UUID(as_uuid=True), ForeignKey("ad_groups.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date(), nullable=False)
    impressions = Column(BigInteger(), nullable=False, server_default="0")
    clicks = Column(BigInteger(), nullable=False, server_default="0")
    spend = Column(Numeric(14, 4), nullable=False, server_default="0")
    sales = Column(Numeric(14, 4), nullable=False, server_default="0")
    orders = Column(Integer(), nullable=False, server_default="0")
    ctr = Column(Numeric(10, 6), nullable=True)
    cpc = Column(Numeric(10, 4), nullable=True)
    acos = Column(Numeric(10, 4), nullable=True)
    roas = Column(Numeric(12, 4), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("ad_group_id", "date", name="uq_agpd_ad_group_date"),
    )


class TargetPerformanceDaily(Base):
    """target_performance_daily — created in migration 004."""
    __tablename__ = "target_performance_daily"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_id = Column(UUID(as_uuid=True), ForeignKey("targets.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date(), nullable=False)
    impressions = Column(BigInteger(), nullable=False, server_default="0")
    clicks = Column(BigInteger(), nullable=False, server_default="0")
    spend = Column(Numeric(12, 2), nullable=False, server_default="0")
    sales = Column(Numeric(12, 2), nullable=False, server_default="0")
    orders = Column(Integer(), nullable=False, server_default="0")
    ctr = Column(Numeric(6, 4), nullable=True)
    cpc = Column(Numeric(8, 4), nullable=True)
    acos = Column(Numeric(6, 2), nullable=True)
    roas = Column(Numeric(6, 2), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("target_id", "date", name="uq_tpd_target_date"),
    )
