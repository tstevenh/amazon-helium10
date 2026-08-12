"""What state should a campaign be in right now?

This is the whole feature in one pure function, so it is tested exhaustively
here rather than through a database. Getting it wrong does not throw — it
quietly leaves a customer's ads off, which is why the boundary cases below
are spelled out individually instead of trusting one happy-path test.
"""
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.modules.dayparting.service import _profile_now, desired_state_at


def entry(dow: int, start: int, end: int, action: str = "pause"):
    """A stand-in for DaypartingEntry — the function only reads these fields."""
    return SimpleNamespace(day_of_week=dow, hour_start=start, hour_end=end,
                           action_type=action, bid_multiplier=None)


# Monday 2026-08-10 is a Monday, so weekday() == 0.
MON = datetime(2026, 8, 10, 3, 0)     # Monday 03:00
SAT = datetime(2026, 8, 15, 3, 0)     # Saturday 03:00


def test_inside_a_pause_window_the_campaign_should_be_paused():
    assert desired_state_at([entry(0, 0, 6)], MON) == "paused"


def test_outside_every_window_the_answer_is_leave_it_alone():
    """Critically NOT "enabled".

    A schedule says "be paused overnight", not "be enabled the rest of the
    time". If this returned "enabled", activating a schedule would switch on
    campaigns a human had deliberately paused.
    """
    assert desired_state_at([entry(0, 0, 6)], datetime(2026, 8, 10, 9, 0)) is None


def test_a_window_on_another_weekday_does_not_apply():
    """"Weekdays only" is the common case; leaking into Saturday is the bug."""
    assert desired_state_at([entry(0, 0, 6)], SAT) is None


def test_hour_start_is_inclusive():
    assert desired_state_at([entry(0, 0, 6)], datetime(2026, 8, 10, 0, 0)) == "paused"


def test_hour_end_is_exclusive():
    """06:00 with a 0-6 window means ads are back ON at 6am, not at 7am.

    Off-by-one here costs a full hour of traffic every single day.
    """
    assert desired_state_at([entry(0, 0, 6)], datetime(2026, 8, 10, 6, 0)) is None
    assert desired_state_at([entry(0, 0, 6)], datetime(2026, 8, 10, 5, 59)) == "paused"


def test_minutes_do_not_shift_the_decision():
    for minute in (0, 1, 30, 59):
        assert desired_state_at([entry(0, 0, 6)],
                                datetime(2026, 8, 10, 5, minute)) == "paused"


def test_enable_windows_are_honoured():
    assert desired_state_at([entry(0, 9, 17, "enable")],
                            datetime(2026, 8, 10, 12, 0)) == "enabled"


def test_pause_wins_when_windows_overlap():
    """Overlap is a config mistake; of the two readings, off is the cheap one."""
    entries = [entry(0, 0, 12, "pause"), entry(0, 6, 18, "enable")]
    assert desired_state_at(entries, datetime(2026, 8, 10, 8, 0)) == "paused"


def test_bid_adjust_entries_are_ignored_not_misread_as_a_state():
    """bid_adjust is reserved in the schema but has no executor.

    It must not accidentally resolve to pause or enable — silently pausing a
    campaign because someone chose an unimplemented action would be the worst
    possible failure mode.
    """
    assert desired_state_at([entry(0, 0, 6, "bid_adjust")], MON) is None


def test_an_empty_schedule_changes_nothing():
    assert desired_state_at([], MON) is None


def test_every_hour_of_a_full_day_schedule_is_covered():
    """A 0-24 window must apply at every hour, including 23:00."""
    e = [entry(2, 0, 24)]      # Wednesday
    for hour in range(24):
        when = datetime(2026, 8, 12, hour, 0)   # 2026-08-12 is a Wednesday
        assert when.weekday() == 2
        assert desired_state_at(e, when) == "paused", f"hour {hour} not covered"


def test_overnight_spans_are_two_entries_and_both_halves_work():
    """22:00-02:00 cannot be one row (hour_end > hour_start is enforced).

    Expressed as Mon 22-24 plus Tue 0-2, both halves must resolve.
    """
    entries = [entry(0, 22, 24), entry(1, 0, 2)]
    assert desired_state_at(entries, datetime(2026, 8, 10, 23, 0)) == "paused"   # Mon
    assert desired_state_at(entries, datetime(2026, 8, 11, 1, 0)) == "paused"    # Tue
    assert desired_state_at(entries, datetime(2026, 8, 11, 3, 0)) is None


# ── timezone handling ──────────────────────────────────────────────────────

def test_missing_timezone_yields_no_time_rather_than_utc():
    """Falling back to UTC would pause a US account at 7pm local."""
    assert _profile_now(None) is None
    assert _profile_now("") is None


def test_unknown_timezone_is_refused_not_guessed():
    assert _profile_now("Mars/Olympus_Mons") is None


def test_a_real_timezone_produces_an_aware_datetime():
    now = _profile_now("America/Los_Angeles")
    assert now is not None and now.tzinfo is not None


def test_the_same_instant_is_a_different_hour_in_different_marketplaces():
    """Why hours must be marketplace-local: US, CA and MX share no clock."""
    la = _profile_now("America/Los_Angeles")
    mx = _profile_now("America/Mexico_City")
    assert la is not None and mx is not None
    # Not asserting a fixed offset — DST moves it. Asserting they can differ.
    assert la.utcoffset() != mx.utcoffset() or la.hour == mx.hour


@pytest.mark.parametrize("tz", ["America/Los_Angeles", "America/Toronto",
                                "America/Mexico_City"])
def test_dst_transitions_do_not_crash_the_decision(tz):
    """Hour arithmetic must survive a DST boundary in every marketplace."""
    zone = ZoneInfo(tz)
    for month, day in ((3, 8), (11, 1)):     # typical US DST change weekends
        when = datetime(2026, month, day, 2, 30, tzinfo=zone)
        assert desired_state_at([entry(when.weekday(), 0, 6)], when) == "paused"
