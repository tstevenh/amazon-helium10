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
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.config import settings
from app.core.amazon_ads_write import (
    AmazonWriteDisabled,
    CampaignStateRefused,
    update_campaign_state,
)
from app.modules.accounts.repository import SellerAccountRepository
from app.modules.accounts.service import AccountService
from app.modules.campaigns.models import Campaign
from app.modules.dayparting.models import (
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

        if desired is None:
            # Outside every window: leave campaigns exactly as a human left them.
            self._record(schedule.id, None, local_str, None, None,
                         OUTCOME_ALREADY_CORRECT, "no window active at this hour")
            return result

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
        token: Optional[str] = None

        for campaign in campaigns:
            result["checked"] += 1
            current = (campaign.status or "").lower()

            if current == desired:
                self._record(schedule.id, campaign.id, local_str, desired, current,
                             OUTCOME_ALREADY_CORRECT)
                continue

            # An archived campaign cannot be re-enabled; never try.
            if current == "archived":
                self._record(schedule.id, campaign.id, local_str, desired, current,
                             OUTCOME_FAILED, "campaign is archived on Amazon")
                result["failed"] += 1
                continue

            if not settings.amazon_write_enabled:
                self._record(schedule.id, campaign.id, local_str, desired, current,
                             OUTCOME_WRITES_DISABLED,
                             "AMAZON_WRITE_ENABLED is false, so no change was sent")
                result["skipped"] += 1
                continue

            try:
                if token is None:
                    token = AccountService(self.db).get_valid_access_token(account)
                outcome = update_campaign_state(
                    token, profile.amazon_profile_id,
                    campaign.amazon_campaign_id, desired.upper(),
                )
            except (AmazonWriteDisabled, CampaignStateRefused) as exc:
                self._record(schedule.id, campaign.id, local_str, desired, current,
                             OUTCOME_WRITES_DISABLED, str(exc))
                result["skipped"] += 1
                continue
            except Exception as exc:
                logger.error("[dayparting] %s: %s", campaign.name, exc)
                self._record(schedule.id, campaign.id, local_str, desired, current,
                             OUTCOME_FAILED, str(exc)[:500])
                result["failed"] += 1
                continue

            if not outcome.get("ok"):
                # 200/207 with a per-item error is a failure, not a success.
                self._record(schedule.id, campaign.id, local_str, desired, current,
                             OUTCOME_FAILED, str(outcome.get("response"))[:500])
                result["failed"] += 1
                continue

            # Only now did Amazon actually change: mirror it locally and log it
            # alongside every other confirmed change to the account.
            campaign.status = desired
            self.execution_repo.record_change(
                profile_id=profile.id,
                entity_type="campaign",
                entity_id=campaign.id,
                amazon_entity_id=campaign.amazon_campaign_id,
                field_changed="state",
                old_value=current,
                new_value=desired,
                suggestion_id=None,
                # The human who activated the schedule owns every change it
                # makes — that is exactly what the approval exception means.
                changed_by=schedule.activated_by,
                source="dayparting",
            )
            self._record(schedule.id, campaign.id, local_str, desired, current,
                         OUTCOME_APPLIED)
            result["changed"] += 1

        return result

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
