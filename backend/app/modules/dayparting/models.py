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
    # pause | enable | decrease_bid | increase_bid
    # ('bid_adjust' is still permitted by the CHECK constraint because 017
    #  created it as a reserved value; the service rejects it as unimplemented.)
    action_type    = Column(String(20), nullable=False)
    # Legacy from 017, never populated. adjust_pct below is the real field.
    bid_multiplier = Column(Numeric(5, 2), nullable=True)
    # Always POSITIVE; direction comes from action_type. A signed percentage
    # plus a direction gives two ways to express "down", and
    # "increase_bid by -20" is a bug waiting to be written.
    adjust_pct     = Column(Numeric(6, 2), nullable=True)
    # Floor and ceiling, as in Helium 10's "Min Bid" box. Both optional.
    min_bid        = Column(Numeric(10, 2), nullable=True)
    max_bid        = Column(Numeric(10, 2), nullable=True)
    created_at     = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class DaypartingBidState(Base):
    """The bid to return to, and the last bid this app wrote.

    Dayparting reconciles: every run asks "what should this be right now?".
    That works for pause because "paused" is a state. It does not work for
    "reduce 20%", which is an operation — re-applying it hourly compounds
    ($0.50 -> 0.40 -> 0.32 -> 0.26) and wrecks the bid within a day.

    Remembering the baseline turns the adjustment into a state:
    target = baseline * (1 +/- pct), clamped. Run it once or fifty times and
    the answer is the same, and outside every window the bid goes back to
    baseline.

    last_written_bid is how a human's edit is noticed. If Amazon's bid is not
    the number this app last wrote, a person changed it, and the row is
    RELEASED rather than overwritten — people outrank schedules. Note this
    detection is only as fresh as the last sync, since the comparison uses the
    locally stored bid.
    """
    __tablename__ = "dayparting_bid_state"

    id               = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    schedule_id      = Column(UUID(as_uuid=True), ForeignKey("dayparting_schedules.id", ondelete="CASCADE"), nullable=False)
    target_id        = Column(UUID(as_uuid=True), ForeignKey("targets.id", ondelete="CASCADE"), nullable=False)
    baseline_bid     = Column(Numeric(10, 2), nullable=False)
    last_written_bid = Column(Numeric(10, 2), nullable=True)
    released_at      = Column(TIMESTAMP(timezone=True), nullable=True)
    released_reason  = Column(Text, nullable=True)
    created_at       = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at       = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


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
