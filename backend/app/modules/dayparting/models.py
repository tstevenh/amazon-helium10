"""ORM models for dayparting (spec §8.7)."""
from sqlalchemy import (
    Boolean, Column, ForeignKey, Numeric, SmallInteger, String, Text,
    TIMESTAMP, func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class DaypartingSchedule(Base):
    """A named set of hour windows applied to specific campaigns.

    is_active defaults to False: creating a schedule must never begin changing
    a live account. Activation is a separate, deliberate act, and who did it is
    recorded because this is the one feature that then runs unattended.
    """
    __tablename__ = "dayparting_schedules"

    id           = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    profile_id   = Column(UUID(as_uuid=True), ForeignKey("ads_profiles.id", ondelete="CASCADE"), nullable=False)
    name         = Column(String(200), nullable=False)
    description  = Column(Text, nullable=True)
    is_active    = Column(Boolean, nullable=False, server_default="false")
    activated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    activated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_by   = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at   = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at   = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    deleted_at   = Column(TIMESTAMP(timezone=True), nullable=True)


class DaypartingScheduleScope(Base):
    """Which campaigns a schedule governs. No rows means it governs nothing.

    Deliberately not "empty means all": a schedule that silently expanded to
    the whole marketplace would be the worst possible default for a feature
    that pauses ads.
    """
    __tablename__ = "dayparting_schedule_scope"

    schedule_id = Column(UUID(as_uuid=True), ForeignKey("dayparting_schedules.id", ondelete="CASCADE"), primary_key=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True)


class DaypartingEntry(Base):
    """One window: on this weekday, between these hours, be in this state.

    A window describes desired STATE, not an event at its edges. See the
    reconciliation note in service.py for why that distinction matters here.
    """
    __tablename__ = "dayparting_entries"

    id             = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    schedule_id    = Column(UUID(as_uuid=True), ForeignKey("dayparting_schedules.id", ondelete="CASCADE"), nullable=False)
    # 0 = Monday .. 6 = Sunday, matching Python's datetime.weekday()
    day_of_week    = Column(SmallInteger, nullable=False)
    # hour_start inclusive, hour_end exclusive, marketplace-local
    hour_start     = Column(SmallInteger, nullable=False)
    hour_end       = Column(SmallInteger, nullable=False)
    # pause | enable | bid_adjust — bid_adjust is reserved, not implemented
    action_type    = Column(String(20), nullable=False)
    bid_multiplier = Column(Numeric(5, 2), nullable=True)
    created_at     = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class DaypartingRun(Base):
    """One reconciliation decision, so "why are my ads off?" is answerable.

    change_log records what Amazon confirmed. This records the reasoning that
    led there, including the runs where nothing needed changing.
    """
    __tablename__ = "dayparting_runs"

    id             = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    schedule_id    = Column(UUID(as_uuid=True), ForeignKey("dayparting_schedules.id", ondelete="CASCADE"), nullable=False)
    campaign_id    = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True)
    ran_at         = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    local_time     = Column(String(40), nullable=True)
    desired_state  = Column(String(20), nullable=True)
    previous_state = Column(String(20), nullable=True)
    # applied | already_correct | skipped_writes_disabled | failed
    outcome        = Column(String(30), nullable=False)
    detail         = Column(Text, nullable=True)
