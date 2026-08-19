"""Dayparting API (spec §21.2: /dayparting-schedules GET/POST/PATCH).

Activation is a separate endpoint from creation on purpose. Creating a schedule
is harmless; activating one hands a piece of your live account to a timer, and
the spec's approval-scope exception is what makes that acceptable. Separating
them means the audit trail records who accepted that, and when.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.campaigns.models import Campaign
from app.modules.dayparting.models import (
    DaypartingEntry,
    DaypartingRun,
    DaypartingSchedule,
    DaypartingScheduleScope,
)
from app.modules.dayparting.service import DaypartingService

router = APIRouter(prefix="/dayparting-schedules", tags=["dayparting"])

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
              "Saturday", "Sunday"]


# ── Schemas ────────────────────────────────────────────────────────────────

class EntryIn(BaseModel):
    day_of_week: int = Field(ge=0, le=6, description="0 = Monday .. 6 = Sunday")
    hour_start:  int = Field(ge=0, le=23, description="inclusive")
    hour_end:    int = Field(ge=1, le=24, description="exclusive")
    # 'bid_adjust' from 017 is deliberately NOT accepted: it was a reserved
    # placeholder with no executor, and storing one would leave a row the
    # scheduler ignores, which reads as "dayparting is broken". decrease_bid
    # and increase_bid replace it and do have an executor.
    action_type: Literal["pause", "enable", "decrease_bid", "increase_bid"]
    # Always positive; the direction is in action_type. Amazon's own placement
    # adjustments cap at 900%, so the same ceiling is used here.
    adjust_pct: Optional[Decimal] = Field(default=None, gt=0, le=900)
    # Optional floor and ceiling, as in Helium 10's "Min Bid" box.
    min_bid: Optional[Decimal] = Field(default=None, gt=0)
    max_bid: Optional[Decimal] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _window_moves_forward(self):
        if self.hour_end <= self.hour_start:
            raise ValueError(
                "hour_end must be after hour_start. For an overnight window "
                "such as 22:00-02:00, add two entries: 22-24 on one day and "
                "0-2 on the next."
            )
        return self

    @model_validator(mode="after")
    def _bid_fields_match_the_action(self):
        is_bid = self.action_type in ("decrease_bid", "increase_bid")
        if is_bid and self.adjust_pct is None:
            raise ValueError(
                f"{self.action_type} needs adjust_pct — a bid window with no "
                f"percentage would do nothing every hour, which looks like a bug."
            )
        if not is_bid and (self.adjust_pct is not None
                           or self.min_bid is not None
                           or self.max_bid is not None):
            raise ValueError(
                f"adjust_pct, min_bid and max_bid only apply to decrease_bid "
                f"and increase_bid, not to {self.action_type}. Silently ignoring "
                f"them would hide a mistake in the schedule."
            )
        if (self.min_bid is not None and self.max_bid is not None
                and self.min_bid > self.max_bid):
            raise ValueError("min_bid cannot be greater than max_bid")
        # A decrease that can never go below its own floor is a no-op the
        # operator almost certainly did not intend.
        if (self.action_type == "decrease_bid" and self.adjust_pct is not None
                and self.adjust_pct >= 100):
            raise ValueError(
                "decrease_bid must be under 100% — a 100% cut would set the bid "
                "to zero, which Amazon rejects. Use a pause window instead."
            )
        return self


class EntryOut(EntryIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    action_type: str
    day_name: str = ""


class ScheduleIn(BaseModel):
    profile_id:  uuid.UUID
    name:        str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    campaign_ids: list[uuid.UUID] = Field(default_factory=list)
    entries:      list[EntryIn] = Field(default_factory=list)


class SchedulePatch(BaseModel):
    name:         Optional[str] = Field(default=None, min_length=1, max_length=200)
    description:  Optional[str] = None
    campaign_ids: Optional[list[uuid.UUID]] = None
    entries:      Optional[list[EntryIn]] = None


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:           uuid.UUID
    profile_id:   uuid.UUID
    name:         str
    description:  Optional[str]
    is_active:    bool
    activated_at: Optional[datetime]
    created_at:   datetime
    campaign_ids: list[uuid.UUID] = []
    entries:      list[EntryOut] = []


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:             uuid.UUID
    campaign_id:    Optional[uuid.UUID]
    ran_at:         datetime
    local_time:     Optional[str]
    desired_state:  Optional[str]
    previous_state: Optional[str]
    outcome:        str
    detail:         Optional[str]


# ── Helpers ────────────────────────────────────────────────────────────────

def _load(db: Session, schedule_id: uuid.UUID) -> DaypartingSchedule:
    schedule = (
        db.query(DaypartingSchedule)
        .filter(DaypartingSchedule.id == schedule_id,
                DaypartingSchedule.deleted_at.is_(None))
        .first()
    )
    if schedule is None:
        raise HTTPException(404, "Schedule not found")
    return schedule


def _serialise(db: Session, schedule: DaypartingSchedule) -> ScheduleOut:
    scope = db.query(DaypartingScheduleScope).filter(
        DaypartingScheduleScope.schedule_id == schedule.id).all()
    entries = db.query(DaypartingEntry).filter(
        DaypartingEntry.schedule_id == schedule.id
    ).order_by(DaypartingEntry.day_of_week, DaypartingEntry.hour_start).all()

    out = ScheduleOut.model_validate(schedule)
    out.campaign_ids = [s.campaign_id for s in scope]
    out.entries = [
        EntryOut(id=e.id, day_of_week=e.day_of_week, hour_start=e.hour_start,
                 hour_end=e.hour_end, action_type=e.action_type,
                 adjust_pct=e.adjust_pct, min_bid=e.min_bid, max_bid=e.max_bid,
                 day_name=_DAY_NAMES[e.day_of_week])
        for e in entries
    ]
    return out


def _replace_scope(db: Session, schedule: DaypartingSchedule,
                   campaign_ids: list[uuid.UUID]) -> None:
    """A campaign outside the schedule's own marketplace is rejected."""
    db.query(DaypartingScheduleScope).filter(
        DaypartingScheduleScope.schedule_id == schedule.id).delete()
    if not campaign_ids:
        return
    found = db.query(Campaign).filter(
        Campaign.id.in_(campaign_ids), Campaign.deleted_at.is_(None)).all()
    by_id = {c.id: c for c in found}
    for cid in campaign_ids:
        campaign = by_id.get(cid)
        if campaign is None:
            raise HTTPException(400, f"Campaign {cid} not found")
        if campaign.profile_id != schedule.profile_id:
            raise HTTPException(
                400,
                f"Campaign '{campaign.name}' belongs to a different marketplace "
                f"than this schedule",
            )
        db.add(DaypartingScheduleScope(schedule_id=schedule.id, campaign_id=cid))


def _replace_entries(db: Session, schedule: DaypartingSchedule,
                     entries: list[EntryIn]) -> None:
    db.query(DaypartingEntry).filter(
        DaypartingEntry.schedule_id == schedule.id).delete()
    for e in entries:
        db.add(DaypartingEntry(
            schedule_id=schedule.id, day_of_week=e.day_of_week,
            hour_start=e.hour_start, hour_end=e.hour_end,
            action_type=e.action_type, adjust_pct=e.adjust_pct,
            min_bid=e.min_bid, max_bid=e.max_bid,
        ))


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ScheduleOut])
def list_schedules(
    profile_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(DaypartingSchedule).filter(DaypartingSchedule.deleted_at.is_(None))
    if profile_id:
        q = q.filter(DaypartingSchedule.profile_id == profile_id)
    return [_serialise(db, s) for s in q.order_by(DaypartingSchedule.created_at.desc()).all()]


@router.post("", response_model=ScheduleOut, status_code=201)
def create_schedule(
    body: ScheduleIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    schedule = DaypartingSchedule(
        profile_id=body.profile_id, name=body.name,
        description=body.description, created_by=user.id,
        is_active=False,   # never active on creation
    )
    db.add(schedule)
    db.flush()
    _replace_scope(db, schedule, body.campaign_ids)
    _replace_entries(db, schedule, body.entries)
    db.commit()
    db.refresh(schedule)
    return _serialise(db, schedule)


@router.patch("/{schedule_id}", response_model=ScheduleOut)
def update_schedule(
    schedule_id: uuid.UUID,
    body: SchedulePatch,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    schedule = _load(db, schedule_id)
    if body.name is not None:
        schedule.name = body.name
    if body.description is not None:
        schedule.description = body.description
    if body.campaign_ids is not None:
        _replace_scope(db, schedule, body.campaign_ids)
    if body.entries is not None:
        _replace_entries(db, schedule, body.entries)
    db.commit()
    db.refresh(schedule)
    return _serialise(db, schedule)


@router.post("/{schedule_id}/activate", response_model=ScheduleOut)
def activate_schedule(
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Hand this schedule to the hourly timer.

    Separate from creation because this is the moment a human accepts the
    spec's approval-scope exception: from here the schedule changes campaign
    state without asking again each hour.
    """
    schedule = _load(db, schedule_id)

    entries = db.query(DaypartingEntry).filter(
        DaypartingEntry.schedule_id == schedule.id).count()
    if entries == 0:
        raise HTTPException(400, "Add at least one time window before activating.")

    scope = db.query(DaypartingScheduleScope).filter(
        DaypartingScheduleScope.schedule_id == schedule.id).count()
    if scope == 0:
        raise HTTPException(
            400,
            "Select at least one campaign before activating. An empty schedule "
            "would do nothing.",
        )

    schedule.is_active = True
    schedule.activated_by = user.id
    schedule.activated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(schedule)
    return _serialise(db, schedule)


@router.post("/{schedule_id}/deactivate", response_model=ScheduleOut)
def deactivate_schedule(
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Stop the timer. Campaigns are left exactly as they are.

    Deliberately does NOT re-enable anything: if a schedule paused campaigns
    overnight and is switched off at 3am, silently turning the ads back on
    would be a surprise spend nobody asked for. The operator decides.
    """
    schedule = _load(db, schedule_id)
    schedule.is_active = False
    db.commit()
    db.refresh(schedule)
    return _serialise(db, schedule)


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    schedule = _load(db, schedule_id)
    schedule.is_active = False
    schedule.deleted_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/{schedule_id}/runs", response_model=list[RunOut])
def list_runs(
    schedule_id: uuid.UUID,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Why the ads are off right now, answerable without reading worker logs."""
    _load(db, schedule_id)
    return (
        db.query(DaypartingRun)
        .filter(DaypartingRun.schedule_id == schedule_id)
        .order_by(DaypartingRun.ran_at.desc())
        .limit(limit)
        .all()
    )


@router.post("/{schedule_id}/run-now")
def run_now(
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Reconcile one schedule immediately.

    Honours is_active: an inactive schedule reports what it *would* do without
    touching Amazon, which is how you test a schedule before trusting it.
    """
    schedule = _load(db, schedule_id)
    if not schedule.is_active:
        from app.modules.dayparting.service import (
            _profile_now, desired_bid_directive_at, desired_state_at,
        )
        from app.modules.accounts.models import AdsProfile

        profile = db.query(AdsProfile).filter(
            AdsProfile.id == schedule.profile_id).first()
        now_local = _profile_now(profile.timezone if profile else None)
        entries = db.query(DaypartingEntry).filter(
            DaypartingEntry.schedule_id == schedule.id).all()
        desired = desired_state_at(entries, now_local) if now_local else None
        directive = desired_bid_directive_at(entries, now_local) if now_local else None

        # A bid-only schedule has no desired STATE at any hour. Reporting only
        # would_set_state would show "null" and read as "this schedule does
        # nothing" — which is how an operator concludes the feature is broken.
        if desired == "paused":
            bid_note = "no bid change — the campaign should be paused right now"
        elif directive is not None:
            bid_note = (
                f"{'decrease' if directive.action == 'decrease_bid' else 'increase'} "
                f"every keyword bid by {directive.pct}% from its baseline"
                + (f", floor ${directive.min_bid}" if directive.min_bid else "")
                + (f", ceiling ${directive.max_bid}" if directive.max_bid else "")
            )
        else:
            bid_note = "restore every keyword bid to its baseline"

        return {
            "dry_run": True,
            "reason": "schedule is not active, so nothing was sent to Amazon",
            "local_time": now_local.strftime("%Y-%m-%d %H:%M %Z") if now_local else None,
            "would_set_state": desired,
            "would_adjust_bids": bid_note,
        }

    result = DaypartingService(db).reconcile_schedule(schedule)
    db.commit()
    return {"dry_run": False, **result}
