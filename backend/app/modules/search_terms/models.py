"""ORM model for search_terms table (Sprint 2)."""
from sqlalchemy import Column, Date, Integer, Numeric, String, TIMESTAMP, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class SearchTerm(Base):
    __tablename__ = "search_terms"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    profile_id = Column(UUID(as_uuid=True), ForeignKey("ads_profiles.id", ondelete="CASCADE"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    ad_group_id = Column(UUID(as_uuid=True), ForeignKey("ad_groups.id", ondelete="SET NULL"), nullable=True)
    search_term = Column(String(500), nullable=False)
    date = Column(Date, nullable=False)
    impressions = Column(Integer, nullable=False, server_default="0")
    clicks = Column(Integer, nullable=False, server_default="0")
    cost = Column(Numeric(12, 4), nullable=False, server_default="0")
    sales = Column(Numeric(12, 4), nullable=False, server_default="0")
    orders = Column(Integer, nullable=False, server_default="0")
    units = Column(Integer, nullable=False, server_default="0")
    ctr = Column(Numeric(8, 6), nullable=False, server_default="0")
    cpc = Column(Numeric(10, 4), nullable=False, server_default="0")
    acos = Column(Numeric(8, 6), nullable=True)
    roas = Column(Numeric(10, 4), nullable=True)
    conversion_rate = Column(Numeric(8, 6), nullable=False, server_default="0")
    last_synced_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
