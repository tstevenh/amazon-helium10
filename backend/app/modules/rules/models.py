"""ORM models for Rules Engine (Sprint 3)."""
from sqlalchemy import Column, ForeignKey, Integer, String, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base


class Rule(Base):
    __tablename__ = "rules"

    id                 = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    profile_id         = Column(UUID(as_uuid=True), ForeignKey("ads_profiles.id", ondelete="CASCADE"), nullable=False)
    name               = Column(String(200), nullable=False)
    description        = Column(Text, nullable=True)
    # negative | harvest | bid
    rule_type          = Column(String(50), nullable=False)
    # enabled | disabled
    status             = Column(String(20), nullable=False, server_default="enabled")
    configuration_json = Column("configuration_json", JSONB, nullable=False, server_default="'{}'")
    created_by         = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at         = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at         = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    deleted_at         = Column(TIMESTAMP(timezone=True), nullable=True)


class RuleExecution(Base):
    __tablename__ = "rule_executions"

    id                    = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    rule_id               = Column(UUID(as_uuid=True), ForeignKey("rules.id", ondelete="CASCADE"), nullable=False)
    profile_id            = Column(UUID(as_uuid=True), ForeignKey("ads_profiles.id", ondelete="CASCADE"), nullable=False)
    started_at            = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    completed_at          = Column(TIMESTAMP(timezone=True), nullable=True)
    # running | completed | failed
    execution_status      = Column(String(20), nullable=False, server_default="running")
    rows_evaluated        = Column(Integer, nullable=False, server_default="0")
    suggestions_generated = Column(Integer, nullable=False, server_default="0")
    error_message         = Column(Text, nullable=True)
    created_at            = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class RuleCampaignScope(Base):
    """Restricts a rule to specific campaigns.

    No rows for a rule means profile-wide — which is how every rule behaved
    before scoping existed, so existing rules are unaffected.
    """
    __tablename__ = "rule_campaign_scope"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    rule_id = Column(UUID(as_uuid=True), ForeignKey("rules.id", ondelete="CASCADE"),
                     nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"),
                         nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
