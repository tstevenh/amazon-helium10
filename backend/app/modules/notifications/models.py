"""ORM models for notifications (spec §8.9)."""
from sqlalchemy import Boolean, Column, ForeignKey, String, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id               = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    event_type       = Column(String(50), nullable=False)
    # slack | email — email is spec'd but has no transport; the API rejects it
    channel          = Column(String(20), nullable=False)
    threshold_config = Column(JSONB, nullable=False, server_default="'{}'")
    is_active        = Column(Boolean, nullable=False, server_default="true")
    created_by       = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at       = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    deleted_at       = Column(TIMESTAMP(timezone=True), nullable=True)


class NotificationLog(Base):
    """Every notification the app produced, delivered or not.

    The point of persisting these is that alerting already existed and still
    failed to inform anyone: an unconfigured webhook writes to stderr, and
    nobody reads stderr. A row here with delivery_status='logged_only' says
    "the app noticed, and had nowhere to say it".
    """
    __tablename__ = "notification_log"

    id                   = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    notification_rule_id = Column(UUID(as_uuid=True), ForeignKey("notification_rules.id", ondelete="SET NULL"), nullable=True)
    event_type           = Column(String(50), nullable=False)
    channel              = Column(String(20), nullable=True)
    subject              = Column(String(300), nullable=True)
    body                 = Column(Text, nullable=True)
    payload              = Column(JSONB, nullable=True)
    # delivered | failed | logged_only
    delivery_status      = Column(String(20), nullable=False)
    error_message        = Column(Text, nullable=True)
    read_at              = Column(TIMESTAMP(timezone=True), nullable=True)
    sent_at              = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class Setting(Base):
    """Key/value overrides for env-var defaults (spec §8.9)."""
    __tablename__ = "settings"

    id         = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    key        = Column(String(100), nullable=False, unique=True)
    value      = Column(JSONB, nullable=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
