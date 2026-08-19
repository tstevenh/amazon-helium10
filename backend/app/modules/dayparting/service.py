"""Dayparting: decide what state each campaign should be in, and enforce it.

WHY RECONCILIATION AND NOT TRIGGERS
-----------------------------------
The obvious design is edge-triggered: at 00:00 fire "pause", at 06:00 fire
"enable". It is also the wrong design here, because the host machine is not
reliably awake — eight scheduled syncs on this account failed with DNS errors
because the laptop was asleep. An edge-triggered scheduler that misses its
06:00 "enable" leaves the ads off until someone notices.

So an entry describes the state a campaign SHOULD be in during a window, and
every run asks "what should this be right now?" and corrects any difference.
Miss ten runs and the eleventh puts everything right. The cost is that the
executor must run often enough to bound the error — hourly means a missed
window is wrong for at most an hour.

TIMEZONES
---------
Hours are local to the marketplace, read from the profile's own timezone.

Note for this account specifically: Amazon reports America/Los_Angeles for all
three profiles (US, CA and MX), so today "6am" is in fact the same instant
everywhere. The per-profile lookup is kept anyway — it is Amazon's value to
change, not ours, and a future EU or JP profile would not share it.

If Amazon never gave us a timezone the schedule is skipped rather than guessed
at: defaulting to UTC would pause a Los Angeles account at 5pm local.

DEFAULT WHEN NO WINDOW MATCHES
------------------------------
Outside every window, a campaign is left ALONE. It is not force-enabled.
A schedule says "be paused overnight", not "be enabled the rest of the time" —
otherwise activating a dayparting schedule would silently switch on campaigns
a human had deliberately paused.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone as tz
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.core.amazon_ads_write import (
    AmazonWriteDisabled,
    CampaignStateRefused,
    update_campaign_state,
    update_keyword_bid,
    update_target_bid,
)
from app.modules.accounts.repository import SellerAccountRepository
from app.modules.accounts.service import AccountService
from app.modules.campaigns.models import AdGroup, Campaign, Target
from app.modules.dayparting.models import (
    DaypartingBidState,
    DaypartingCampaignState,
    DaypartingEntry,
    DaypartingRun,
    DaypartingSchedule,
    DaypartingScheduleScope,
)
from app.modules.execution.repository import ExecutionRepository

logger = logging.getLogger(__name__)

# Only these two are meaningful as a desired state. bid_adjust is reserved in
# the schema but has no executor, and is rejected at the API instead of being
# silently ignored here.
_ACTION_TO_STATE = {"pause": "paused", "enable": "enabled"}

OUTCOME_APPLIED = "applied"
OUTCOME_ALREADY_CORRECT = "already_correct"
OUTCOME_WRITES_DISABLED = "skipped_writes_disabled"
OUTCOME_FAILED = "failed"
OUTCOME_NO_TIMEZONE = "skipped_no_timezone"
# Bid-specific outcomes. Distinct from the state ones so "why is this bid what
# it is?" is answerable from dayparting_runs alone.
OUTCOME_BID_RELEASED = "bid_released_manual_edit"
OUTCOME_BID_CAPPED = "bid_writes_capped"
OUTCOME_STATE_RELEASED = "state_released_manual_edit"


BID_ACTIONS = ("decrease_bid", "increase_bid")

# Amazon's absolute floor for Sponsored Products. A request below it is
# rejected per-item, which surfaces as a failed run rather than a silent no-op.
#
# Known limitation: this is the USD floor. CAD and MXN floors are higher, so a
# very aggressive decrease on those marketplaces can be refused by Amazon. The
# refusal is recorded and visible; it is not silently swallowed.
AMAZON_MIN_BID = Decimal("0.02")

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class BidDirective:
    """A bid adjustment a window wants applied, as a pure value."""
    action: str                    # decrease_bid | increase_bid
    pct: Decimal                   # always positive
    min_bid: Optional[Decimal]
    max_bid: Optional[Decimal]


def desired_bid(baseline: Decimal, directive: BidDirective) -> Decimal:
    """The bid this target should hold right now, computed FROM THE BASELINE.

    Deriving from the baseline rather than from the current bid is the whole
    point. Dayparting re-runs hourly, so applying "-20%" to whatever the bid
    happens to be would compound: 0.50 -> 0.40 -> 0.32 -> 0.26 -> ... and the
    bid would be destroyed within a day, then start lower again tomorrow.
    From the baseline, the answer is 0.40 no matter how many times it runs.

    Clamp order matters: the operator's own min/max is applied first, and
    Amazon's hard floor last, so a floor of $0.01 cannot produce a request
    Amazon will reject.
    """
    baseline = Decimal(str(baseline))
    factor = (
        (Decimal(1) - directive.pct / Decimal(100))
        if directive.action == "decrease_bid"
        else (Decimal(1) + directive.pct / Decimal(100))
    )
    value = baseline * factor

    if directive.min_bid is not None:
        value = max(value, Decimal(str(directive.min_bid)))
    if directive.max_bid is not None:
        value = min(value, Decimal(str(directive.max_bid)))

    value = max(value, AMAZON_MIN_BID)
    # Amazon takes two decimal places; quantize before comparing to a stored
    # bid, or "already correct" would never be true and every run would write.
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def desired_bid_directive_at(
    entries: list[DaypartingEntry], when: datetime
) -> Optional[BidDirective]:
    """The bid adjustment wanted at this local time, or None for "baseline".

    None means "no bid window is active", which the reconciler reads as
    "restore the baseline" — not "leave it alone". Leaving it alone would let
    yesterday's discount persist forever, which is the drift the team would
    have to undo by hand.

    Overlapping bid windows are a configuration error. As with pause winning
    over enable, the cheaper reading wins: whichever directive yields the
    LOWEST bid from a nominal baseline is chosen, so a mistake costs less
    money rather than more.
    """
    dow = when.weekday()
    hour = when.hour

    matched: list[BidDirective] = []
    for e in entries:
        if e.day_of_week != dow or e.action_type not in BID_ACTIONS:
            continue
        if not (e.hour_start <= hour < e.hour_end):
            continue
        if e.adjust_pct is None:
            # The CHECK constraint forbids this; belt and braces, because a
            # None percentage would raise mid-reconcile for every target.
            logger.error("[dayparting] entry %s is %s with no adjust_pct — ignored",
                         e.id, e.action_type)
            continue
        matched.append(BidDirective(
            action=e.action_type,
            pct=Decimal(str(e.adjust_pct)),
            min_bid=Decimal(str(e.min_bid)) if e.min_bid is not None else None,
            max_bid=Decimal(str(e.max_bid)) if e.max_bid is not None else None,
        ))

    if not matched:
        return None
    if len(matched) == 1:
        return matched[0]
    probe = Decimal("1.00")
    return min(matched, key=lambda d: desired_bid(probe, d))


def desired_state_at(entries: list[DaypartingEntry], when: datetime) -> Optional[str]:
    """The state the schedule wants at this local time, or None for "leave it".

    Pure function of (entries, time) so the decision is testable without a
    database, a clock, or Amazon.

    When windows overlap, `pause` wins. Overlap is a configuration mistake, and
    of the two possible readings, "leave the ads off" is the cheaper one.
    """
    dow = when.weekday()          # 0 = Monday, matching the stored values
    hour = when.hour

    matched: list[str] = []
    for e in entries:
        if e.day_of_week != dow:
            continue
        # hour_start inclusive, hour_end exclusive
        if e.hour_start <= hour < e.hour_end:
            state = _ACTION_TO_STATE.get(e.action_type)
            if state is not None:
                matched.append(state)

    if not matched:
        return None
    return "paused" if "paused" in matched else "enabled"


def _profile_now(timezone_name: Optional[str]) -> Optional[datetime]:
    """Current time in the marketplace's timezone, or None if unknown."""
    if not timezone_name:
        return None
    try:
        return datetime.now(ZoneInfo(timezone_name))
    except (ZoneInfoNotFoundError, ValueError):
        logger.error("[dayparting] unusable timezone %r", timezone_name)
        return None


class DaypartingService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.execution_repo = ExecutionRepository(db)

    def _record(
        self,
        schedule_id,
        campaign_id,
        local_time: Optional[str],
        desired: Optional[str],
        previous: Optional[str],
        outcome: str,
        detail: Optional[str] = None,
    ) -> None:
        self.db.add(DaypartingRun(
            schedule_id=schedule_id, campaign_id=campaign_id,
            local_time=local_time, desired_state=desired,
            previous_state=previous, outcome=outcome, detail=detail,
        ))

    def reconcile_schedule(self, schedule: DaypartingSchedule) -> dict[str, Any]:
        """Bring every campaign in one schedule's scope to its desired state."""
        result = {"schedule": schedule.name, "checked": 0, "changed": 0,
                  "skipped": 0, "failed": 0}

        profile = schedule.profile if hasattr(schedule, "profile") else None
        if profile is None:
            from app.modules.accounts.models import AdsProfile
            profile = self.db.query(AdsProfile).filter(
                AdsProfile.id == schedule.profile_id
            ).first()
        if profile is None:
            self._record(schedule.id, None, None, None, None, OUTCOME_FAILED,
                         "profile not found")
            result["failed"] += 1
            return result

        now_local = _profile_now(profile.timezone)
        if now_local is None:
            # Guessing UTC here would pause a US account at 7pm local.
            self._record(schedule.id, None, None, None, None, OUTCOME_NO_TIMEZONE,
                         f"profile has no usable timezone (got {profile.timezone!r})")
            result["skipped"] += 1
            return result

        local_str = now_local.strftime("%Y-%m-%d %H:%M %Z")
        entries = self.db.query(DaypartingEntry).filter(
            DaypartingEntry.schedule_id == schedule.id
        ).all()
        desired = desired_state_at(entries, now_local)
        bid_directive = desired_bid_directive_at(entries, now_local)

        # NOTE: no early return when `desired` is None any more. A schedule with
        # only bid windows has no desired state at any hour, and returning here
        # would mean bids were never restored to baseline — the discount would
        # persist forever, which is exactly the drift this design avoids.

        campaign_ids = [
            row.campaign_id for row in self.db.query(DaypartingScheduleScope)
            .filter(DaypartingScheduleScope.schedule_id == schedule.id).all()
        ]
        if not campaign_ids:
            self._record(schedule.id, None, local_str, desired, None,
                         OUTCOME_ALREADY_CORRECT, "schedule has no campaigns in scope")
            return result

        campaigns = self.db.query(Campaign).filter(
            Campaign.id.in_(campaign_ids), Campaign.deleted_at.is_(None)
        ).all()

        account = SellerAccountRepository(self.db).get_by_id(profile.seller_account_id)
        # One token for the whole run, fetched on first actual need. Held in a
        # box so the bid pass below can share it with the state pass rather
        # than refreshing twice.
        token_box: list[Optional[str]] = [None]

        def get_token() -> str:
            if token_box[0] is None:
                token_box[0] = AccountService(self.db).get_valid_access_token(account)
            return token_box[0]

        self._reconcile_states(
            schedule=schedule, profile=profile, campaigns=campaigns,
            desired=desired, local_str=local_str, get_token=get_token,
            result=result,
        )


        # ── Bid pass ───────────────────────────────────────────────────────
        # Skipped entirely while the schedule wants these campaigns paused:
        # the ads are off, so the bid is irrelevant, and restoring baselines on
        # a paused campaign would burn thousands of writes for no effect. The
        # bid is corrected within the hour after it is enabled again.
        if desired != "paused":
            self._reconcile_bids(
                schedule=schedule, profile=profile, campaigns=campaigns,
                directive=bid_directive, local_str=local_str,
                get_token=get_token, result=result,
            )

        return result


    # ── Campaign state reconciliation ──────────────────────────────────────
    def _reconcile_states(
        self,
        schedule: DaypartingSchedule,
        profile,
        campaigns: list[Campaign],
        desired: Optional[str],
        local_str: str,
        get_token,
        result: dict[str, Any],
    ) -> None:
        """Bring every in-scope campaign to the state this hour calls for.

        `desired` None means no pause/enable window is active. That does NOT
        mean "leave everything alone": it means UNDO WHAT THIS SCHEDULE DID.

        The distinction is the whole point. Leaving it alone meant a schedule
        with only a pause window switched the ads off at midnight and never
        switched them back on — silently, every day, forever. Making the
        unpainted hours mean "enabled" instead would switch on campaigns a
        human paused deliberately, which is worse.

        So the app restores only its own changes. A campaign this schedule never
        touched has no state row, and therefore nothing to restore.
        """
        states = {
            st.campaign_id: st
            for st in self.db.query(DaypartingCampaignState).filter(
                DaypartingCampaignState.schedule_id == schedule.id
            ).all()
        }

        for campaign in campaigns:
            result["checked"] += 1
            current = (campaign.status or "").lower()
            state = states.get(campaign.id)

            # An archived campaign cannot be re-enabled; never try.
            if current == "archived":
                if desired is not None:
                    self._record(schedule.id, campaign.id, local_str, desired,
                                 current, OUTCOME_FAILED,
                                 "campaign is archived on Amazon")
                    result["failed"] += 1
                continue

            # Drift: somebody changed the campaign outside this app. Compared
            # against what the app last wrote, so it cannot fire on our own
            # changes, and only as fresh as the last sync.
            if (state is not None and state.released_at is None
                    and state.last_written_status is not None
                    and current != state.last_written_status):
                state.released_at = datetime.now(tz.utc)
                state.released_reason = (
                    f"campaign is {current} but this schedule last set "
                    f"{state.last_written_status} — changed outside the app, so "
                    f"the schedule stopped managing it"
                )
                self._record(schedule.id, campaign.id, local_str, desired,
                             current, OUTCOME_STATE_RELEASED, state.released_reason)
                self._notify_released(
                    schedule,
                    [f"campaign '{campaign.name}': "
                     f"{state.last_written_status} -> {current}"],
                    noun="campaign",
                )
                continue

            if state is not None and state.released_at is not None:
                continue   # a human owns this campaign now

            if desired is not None:
                target = desired
            elif state is not None and state.last_written_status is not None:
                # No window applies: put back what was there before we changed
                # it. Only reachable for campaigns this schedule actually wrote.
                target = state.baseline_status
            else:
                continue   # never touched by this schedule — leave it alone

            if current == target:
                self._record(schedule.id, campaign.id, local_str, target, current,
                             OUTCOME_ALREADY_CORRECT)
                continue

            if not settings.amazon_write_enabled:
                self._record(schedule.id, campaign.id, local_str, target, current,
                             OUTCOME_WRITES_DISABLED,
                             "AMAZON_WRITE_ENABLED is false, so no change was sent")
                result["skipped"] += 1
                continue

            try:
                outcome = update_campaign_state(
                    get_token(), profile.amazon_profile_id,
                    campaign.amazon_campaign_id, target.upper(),
                )
            except (AmazonWriteDisabled, CampaignStateRefused) as exc:
                self._record(schedule.id, campaign.id, local_str, target, current,
                             OUTCOME_WRITES_DISABLED, str(exc))
                result["skipped"] += 1
                continue
            except Exception as exc:
                logger.error("[dayparting] %s: %s", campaign.name, exc)
                self._record(schedule.id, campaign.id, local_str, target, current,
                             OUTCOME_FAILED, str(exc)[:500])
                result["failed"] += 1
                continue

            if not outcome.get("ok"):
                # 200/207 with a per-item error is a failure, not a success.
                # last_written_status is deliberately NOT updated here: recording
                # a write Amazon rejected would make the next run see phantom
                # drift and release a campaign nobody touched.
                self._record(schedule.id, campaign.id, local_str, target, current,
                             OUTCOME_FAILED, str(outcome.get("response"))[:500])
                result["failed"] += 1
                continue

            # Only now did Amazon actually change.
            if state is None:
                # First change this schedule has made. `current` is the status a
                # human left it in, so that is what we owe them back.
                state = DaypartingCampaignState(
                    schedule_id=schedule.id, campaign_id=campaign.id,
                    baseline_status=current if current in ("enabled", "paused") else "enabled",
                )
                self.db.add(state)
                states[campaign.id] = state
            state.last_written_status = target
            state.updated_at = datetime.now(tz.utc)

            campaign.status = target
            self.execution_repo.record_change(
                profile_id=profile.id,
                entity_type="campaign",
                entity_id=campaign.id,
                amazon_entity_id=campaign.amazon_campaign_id,
                field_changed="state",
                old_value=current,
                new_value=target,
                suggestion_id=None,
                # The human who activated the schedule owns every change it
                # makes — that is exactly what the approval exception means.
                changed_by=schedule.activated_by,
                source="dayparting",
            )
            self._record(schedule.id, campaign.id, local_str, target, current,
                         OUTCOME_APPLIED,
                         None if desired is not None
                         else f"restored to {target} — no window active at this hour")
            result["changed"] += 1

    # ── Bid reconciliation ─────────────────────────────────────────────────
    def _reconcile_bids(
        self,
        schedule: DaypartingSchedule,
        profile,
        campaigns: list[Campaign],
        directive: Optional[BidDirective],
        local_str: str,
        get_token,
        result: dict[str, Any],
    ) -> None:
        """Bring every in-scope keyword to the bid this hour calls for.

        `directive` None means no bid window is active, which means RESTORE THE
        BASELINE — not "leave it". Leaving it would let a discount outlive its
        window and compound day over day.
        """
        campaign_by_id = {c.id: c for c in campaigns}
        # Only enabled campaigns. A paused or archived campaign serves no ads,
        # so its bids do not matter, and skipping them keeps the write volume
        # proportional to what is actually running.
        live_ids = [c.id for c in campaigns if (c.status or "").lower() == "enabled"]
        if not live_ids:
            return

        targets = (
            self.db.query(Target)
            .join(AdGroup, AdGroup.id == Target.ad_group_id)
            .filter(
                AdGroup.campaign_id.in_(live_ids),
                Target.deleted_at.is_(None),
                AdGroup.deleted_at.is_(None),
                Target.bid.isnot(None),
                # Paused keywords cost nothing; adjusting them is pure waste.
                func.lower(Target.status) == "enabled",
            )
            .all()
        )
        if not targets:
            return

        states = {
            st.target_id: st
            for st in self.db.query(DaypartingBidState).filter(
                DaypartingBidState.schedule_id == schedule.id
            ).all()
        }

        ag_to_campaign = {
            ag.id: ag.campaign_id
            for ag in self.db.query(AdGroup).filter(AdGroup.campaign_id.in_(live_ids)).all()
        }

        cap = settings.dayparting_max_bid_writes_per_run
        writes = 0
        released: list[str] = []
        capped = 0

        for target in targets:
            campaign = campaign_by_id.get(ag_to_campaign.get(target.ad_group_id))
            current = Decimal(str(target.bid))
            state = states.get(target.id)

            if state is None:
                # First time this schedule has seen the keyword. The app has
                # never written to it, so whatever Amazon holds IS the human's
                # own number — safe to adopt as the baseline.
                state = DaypartingBidState(
                    schedule_id=schedule.id, target_id=target.id,
                    baseline_bid=current, last_written_bid=None,
                )
                self.db.add(state)
                states[target.id] = state

            if state.released_at is not None:
                continue   # a human owns this keyword now

            # Drift = somebody changed the bid outside this app. Detected by
            # comparing against what the app last wrote, so it cannot fire on
            # the app's own changes. Only as fresh as the last sync, since
            # target.bid is the locally stored value.
            if state.last_written_bid is not None and \
                    current != Decimal(str(state.last_written_bid)):
                state.released_at = datetime.now(tz.utc)
                state.released_reason = (
                    f"bid is {current} but this schedule last wrote "
                    f"{state.last_written_bid} — changed outside the app, so the "
                    f"schedule stopped managing it"
                )
                released.append(f"{target.expression_text or target.id}: "
                                f"{state.last_written_bid} -> {current}")
                self._record(schedule.id, campaign.id if campaign else None,
                             local_str, None, str(current), OUTCOME_BID_RELEASED,
                             state.released_reason)
                continue

            wanted = (
                desired_bid(Decimal(str(state.baseline_bid)), directive)
                if directive is not None
                else Decimal(str(state.baseline_bid)).quantize(_CENT)
            )

            if current == wanted:
                continue   # already right; do not spend a write saying so

            if not settings.amazon_write_enabled:
                result["skipped"] += 1
                continue

            if writes >= cap:
                capped += 1
                continue

            try:
                writer = (
                    update_keyword_bid if target.target_kind == "keyword"
                    else update_target_bid
                )
                outcome = writer(
                    get_token(), profile.amazon_profile_id,
                    int(target.amazon_target_id), float(wanted),
                )
            except (AmazonWriteDisabled, ValueError) as exc:
                self._record(schedule.id, campaign.id if campaign else None,
                             local_str, str(wanted), str(current),
                             OUTCOME_WRITES_DISABLED, str(exc)[:500])
                result["skipped"] += 1
                continue
            except Exception as exc:
                logger.error("[dayparting] bid write failed for target %s: %s",
                             target.id, exc)
                self._record(schedule.id, campaign.id if campaign else None,
                             local_str, str(wanted), str(current),
                             OUTCOME_FAILED, str(exc)[:500])
                result["failed"] += 1
                continue

            writes += 1

            if not outcome.get("ok"):
                # 200/207 with a per-item error is a failure. Crucially,
                # last_written_bid is NOT updated here — recording a write that
                # Amazon rejected would make the next run see "drift" and
                # release a keyword nobody touched.
                self._record(schedule.id, campaign.id if campaign else None,
                             local_str, str(wanted), str(current),
                             OUTCOME_FAILED, str(outcome.get("response"))[:500])
                result["failed"] += 1
                continue

            target.bid = wanted
            state.last_written_bid = wanted
            state.updated_at = datetime.now(tz.utc)
            self.execution_repo.record_change(
                profile_id=profile.id,
                entity_type="target",
                entity_id=target.id,
                amazon_entity_id=target.amazon_target_id,
                field_changed="bid",
                old_value=str(current),
                new_value=str(wanted),
                suggestion_id=None,
                changed_by=schedule.activated_by,
                source="dayparting",
            )
            self._record(schedule.id, campaign.id if campaign else None,
                         local_str, str(wanted), str(current), OUTCOME_APPLIED,
                         f"bid {current} -> {wanted}"
                         + (f" ({directive.action} {directive.pct}% from baseline "
                            f"{state.baseline_bid})" if directive else " (restored to baseline)"))
            result["changed"] += 1

        if capped:
            # Never silently truncate. A reconcile that stopped early but
            # reported success would read as "everything is at the right bid".
            msg = (f"{capped} keyword(s) not written this run: hit the "
                   f"{cap}-write cap (dayparting_max_bid_writes_per_run). "
                   f"They will be picked up on the next run.")
            logger.warning("[dayparting] %s", msg)
            self._record(schedule.id, None, local_str, None, None,
                         OUTCOME_BID_CAPPED, msg)
            result["skipped"] += capped

        if released:
            self._notify_released(schedule, released)

    def _notify_released(
        self, schedule: DaypartingSchedule, released: list[str],
        noun: str = "keyword",
    ) -> None:
        """Tell a human that the schedule let go of something it was managing.

        Releasing is the app deferring to a person, not a failure, so it gets
        its own event type — labelling it 'dayparting_failed' would train the
        team to ignore real failures.
        """
        from app.modules.notifications.service import NotificationService

        shown = released[:20]
        body = "\n".join(shown)
        if len(released) > len(shown):
            body += f"\n… and {len(released) - len(shown)} more"
        try:
            NotificationService(self.db).notify(
                "dayparting_released",
                subject=(f"Dayparting released {len(released)} {noun}(s) in "
                         f"'{schedule.name}' after a manual change"),
                body=(body + f"\n\nThese {noun}s were changed outside the app, so "
                      f"the schedule stopped managing them. Nothing was "
                      f"overwritten. Remove and re-add them to the schedule to "
                      f"hand control back."),
            )
        except Exception as exc:
            # A notification failure must not roll back confirmed bid changes.
            logger.error("[dayparting] could not notify about released targets: %s", exc)

    def reconcile_all_active(self) -> dict[str, Any]:
        """Every active schedule. One bad schedule must not stop the others."""
        schedules = self.db.query(DaypartingSchedule).filter(
            DaypartingSchedule.is_active.is_(True),
            DaypartingSchedule.deleted_at.is_(None),
        ).all()

        summary = {"schedules": len(schedules), "changed": 0, "checked": 0,
                   "skipped": 0, "failed": 0, "details": []}
        for schedule in schedules:
            try:
                one = self.reconcile_schedule(schedule)
                # Commit per schedule: the failure path below rolls back, which
                # would otherwise discard schedules that already succeeded.
                self.db.commit()
                for key in ("checked", "changed", "skipped", "failed"):
                    summary[key] += one[key]
                summary["details"].append(one)
            except Exception as exc:
                logger.error("[dayparting] schedule %s failed: %s", schedule.id, exc)
                self.db.rollback()
                summary["failed"] += 1
                summary["details"].append({"schedule": schedule.name, "error": str(exc)})
        return summary
