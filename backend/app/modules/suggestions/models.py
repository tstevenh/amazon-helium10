"""ORM model for suggestions (Sprint 2.5 + Sprint 3)."""
from sqlalchemy import Column, ForeignKey, Integer, Numeric, String, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base


class Suggestion(Base):
    __tablename__ = "suggestions"

    id              = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    profile_id      = Column(UUID(as_uuid=True), ForeignKey("ads_profiles.id", ondelete="CASCADE"), nullable=False)
    campaign_id     = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    ad_group_id     = Column(UUID(as_uuid=True), ForeignKey("ad_groups.id", ondelete="SET NULL"), nullable=True)
    search_term     = Column(String(500), nullable=False)
    # negative_exact | negative_phrase | keyword_exact | keyword_phrase | keyword_broad
    # bid_decrease   | bid_increase
    suggestion_type = Column(String(50), nullable=False)
    # negative | harvest | bid
    kind            = Column(String(20), nullable=False)
    reason          = Column(String(1000), nullable=False)
    metrics_snapshot = Column(JSONB, nullable=False, server_default="'{}'")
    # pending | approved | rejected
    status          = Column(String(20), nullable=False, server_default="pending")
    resolved_by     = Column(UUID(as_uuid=True), nullable=True)
    resolved_at     = Column(TIMESTAMP(timezone=True), nullable=True)
    # ── Added by migration 014: makes a suggestion machine-actionable.
    # Without these a suggestion can describe a change in prose but not
    # express one the execution job can act on.
    target_id       = Column(UUID(as_uuid=True), ForeignKey("targets.id", ondelete="SET NULL"), nullable=True)
    current_value   = Column(JSONB, nullable=True)
    suggested_value = Column(JSONB, nullable=True)
    priority_score  = Column(Integer, nullable=True)
    executed_at     = Column(TIMESTAMP(timezone=True), nullable=True)

    created_at      = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at      = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    # ── Sprint 2.5 fields ────────────────────────────────────────────────────
    confidence_score = Column(Integer, nullable=False, server_default="0")
    campaign_count   = Column(Integer, nullable=False, server_default="1")
    ad_group_count   = Column(Integer, nullable=False, server_default="1")
    total_spend      = Column(Numeric(12, 4), nullable=False, server_default="0")
    total_sales      = Column(Numeric(12, 4), nullable=False, server_default="0")
    total_orders     = Column(Integer, nullable=False, server_default="0")

    # ── Sprint 3 fields — source tracking ────────────────────────────────────
    # engine = built-in suggestion engine | rule = rules engine
    source_type      = Column(String(20), nullable=False, server_default="engine")
    source_rule_id   = Column(UUID(as_uuid=True), ForeignKey("rules.id", ondelete="SET NULL"), nullable=True)
    source_rule_name = Column(String(200), nullable=True)
