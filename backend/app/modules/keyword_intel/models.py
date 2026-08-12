"""ORM models for Keyword Intelligence (spec Part 17).

Shares nothing with the core PPC schema by design, so this module cannot
destabilise campaign syncing or the rules engine.
"""
from sqlalchemy import (
    Column, Date, ForeignKey, Integer, Numeric, String, Text, TIMESTAMP, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.database import Base


class KiSnapshot(Base):
    """One uploaded export. Manual by design — nothing fetches these."""
    __tablename__ = "ki_snapshots"

    id                = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    source_type       = Column(String(30), nullable=False)
    uploaded_by       = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at       = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    # What the data represents, not when it arrived.
    snapshot_date     = Column(Date, nullable=False)
    original_filename = Column(String(500), nullable=True)
    file_hash         = Column(String(64), nullable=True)
    row_count         = Column(Integer, nullable=False, server_default="0")
    # processing | completed | failed
    status            = Column(String(20), nullable=False, server_default="processing")
    error_message     = Column(Text, nullable=True)


class KiSnapshotAsin(Base):
    __tablename__ = "ki_snapshot_asins"

    snapshot_id = Column(UUID(as_uuid=True), ForeignKey("ki_snapshots.id", ondelete="CASCADE"), primary_key=True)
    asin        = Column(String(20), primary_key=True)


class KiKeyword(Base):
    """Stable id per keyword, keyed on normalized text so trends never split."""
    __tablename__ = "ki_keywords"

    id              = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    keyword_text    = Column(Text, nullable=False)
    normalized_text = Column(Text, nullable=False)
    first_seen_at   = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class KiKeywordMetric(Base):
    """The fact table: one row per keyword x ASIN x snapshot."""
    __tablename__ = "ki_keyword_metrics"

    id                       = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    snapshot_id              = Column(UUID(as_uuid=True), ForeignKey("ki_snapshots.id", ondelete="CASCADE"), nullable=False)
    keyword_id               = Column(UUID(as_uuid=True), ForeignKey("ki_keywords.id", ondelete="CASCADE"), nullable=False)
    asin                     = Column(String(20), nullable=True)
    search_volume            = Column(Integer, nullable=True)
    search_volume_trend_pct  = Column(Numeric(10, 2), nullable=True)
    organic_rank             = Column(Integer, nullable=True)
    sponsored_rank           = Column(Integer, nullable=True)
    competing_products_count = Column(Integer, nullable=True)
    sponsored_asins_count    = Column(Integer, nullable=True)
    cpc                      = Column(Numeric(10, 2), nullable=True)
    title_density            = Column(Integer, nullable=True)
    relevance_score          = Column(Numeric(10, 2), nullable=True)
    estimated_sales          = Column(Integer, nullable=True)
    # Keeps every original column, so unmodelled fields are never lost.
    raw_row                  = Column(JSONB, nullable=True)
    created_at               = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class KiColumnMapping(Base):
    """A saved {our_field: their_column} map, so Custom CSV needs no new code."""
    __tablename__ = "ki_column_mappings"

    id           = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name         = Column(String(200), nullable=False)
    source_type  = Column(String(30), nullable=False)
    mapping_json = Column(JSONB, nullable=False)
    created_by   = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at   = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class ProductListing(Base):
    """Manually maintained listing copy (spec §17.3).

    last_updated_at is load-bearing: the spec asks for it explicitly so an
    operator can judge staleness rather than trusting a possibly-ancient row.
    """
    __tablename__ = "product_listings"

    id               = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    asin             = Column(String(20), nullable=False, unique=True)
    title            = Column(Text, nullable=True)
    bullet_points    = Column(ARRAY(Text), nullable=True)
    backend_keywords = Column(Text, nullable=True)
    last_updated_by  = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_updated_at  = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
