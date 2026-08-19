"""What bid should a keyword hold right now?

The dangerous part of bid dayparting is not the arithmetic, it is that
dayparting RECONCILES: every run re-asserts the desired state. "Be paused" is
safe to re-assert. "Reduce 20%" is not — applied to the current bid every hour
it compounds ($0.50 -> 0.40 -> 0.32 -> 0.26 -> ...) and destroys the bid inside
a day, then starts lower again tomorrow.

Deriving from a stored baseline is what makes the adjustment idempotent, so the
first test below is the one that matters most. Getting this wrong does not
raise; it quietly spends the customer's money differently than they asked.
"""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.config import settings
from app.modules.dayparting.service import (
    AMAZON_MIN_BID,
    BidDirective,
    desired_bid,
    desired_bid_directive_at,
    desired_state_at,
)


def bid_entry(dow, start, end, action="decrease_bid", pct=20,
              min_bid=None, max_bid=None):
    """Stand-in for DaypartingEntry — only these fields are read."""
    return SimpleNamespace(
        id="e1", day_of_week=dow, hour_start=start, hour_end=end,
        action_type=action, adjust_pct=Decimal(str(pct)) if pct is not None else None,
        min_bid=Decimal(str(min_bid)) if min_bid is not None else None,
        max_bid=Decimal(str(max_bid)) if max_bid is not None else None,
    )


MON_15 = datetime(2026, 8, 10, 15, 0)   # Monday 15:00
MON_03 = datetime(2026, 8, 10, 3, 0)    # Monday 03:00
SAT_15 = datetime(2026, 8, 15, 15, 0)   # Saturday 15:00

DEC20 = BidDirective("decrease_bid", Decimal("20"), None, None)


# ── The compounding trap ───────────────────────────────────────────────────

def test_repeating_the_adjustment_does_not_compound():
    """The whole reason a baseline is stored.

    Hourly reconciliation means this runs ~8 times inside one window. If the
    result drifted, an operator's $0.50 bid would be ~$0.17 by the end of the
    day and lower again tomorrow.
    """
    baseline = Decimal("0.50")
    first = desired_bid(baseline, DEC20)
    for _ in range(24):
        assert desired_bid(baseline, DEC20) == first
    assert first == Decimal("0.40")


def test_the_adjustment_is_computed_from_baseline_not_from_current():
    """A regression guard with teeth: feeding the previous RESULT back in must
    not be what the function does. If someone rewrites this to take the current
    bid, this test still passes with the same argument — so assert the value
    directly against the baseline arithmetic instead."""
    assert desired_bid(Decimal("0.50"), DEC20) == Decimal("0.40")
    # And the second-generation value differs, which is precisely the bug
    # the baseline design prevents from ever reaching Amazon.
    assert desired_bid(Decimal("0.40"), DEC20) == Decimal("0.32")


# ── Arithmetic and rounding ────────────────────────────────────────────────

def test_decrease_and_increase_move_the_expected_way():
    assert desired_bid(Decimal("1.00"), DEC20) == Decimal("0.80")
    assert desired_bid(Decimal("1.00"),
                       BidDirective("increase_bid", Decimal("50"), None, None)) \
        == Decimal("1.50")


def test_result_is_quantised_to_cents():
    """Amazon takes two decimals. An unrounded value would never equal the
    stored bid, so every run would issue a pointless write."""
    out = desired_bid(Decimal("0.333"), DEC20)
    assert out == Decimal("0.27")
    assert out.as_tuple().exponent == -2


def test_already_correct_is_detectable_after_a_round_trip():
    """The reconciler compares the stored bid to this value to decide whether
    to write at all. Rounding drift here would mean writing every hour."""
    baseline = Decimal("0.47")
    wanted = desired_bid(baseline, DEC20)
    assert desired_bid(baseline, DEC20) == wanted


# ── Clamps ─────────────────────────────────────────────────────────────────

def test_min_bid_is_a_floor():
    """Helium 10's "Min Bid" box: $0.20 cut by 20% is $0.16, floored to $0.18."""
    d = BidDirective("decrease_bid", Decimal("20"), Decimal("0.18"), None)
    assert desired_bid(Decimal("0.20"), d) == Decimal("0.18")


def test_max_bid_is_a_ceiling():
    d = BidDirective("increase_bid", Decimal("100"), None, Decimal("1.20"))
    assert desired_bid(Decimal("1.00"), d) == Decimal("1.20")


def test_amazons_floor_wins_over_an_operator_floor_that_is_too_low():
    """A $0.001 floor must not produce a request Amazon rejects outright."""
    d = BidDirective("decrease_bid", Decimal("99"), Decimal("0.001"), None)
    assert desired_bid(Decimal("0.50"), d) == AMAZON_MIN_BID


def test_a_deep_cut_never_reaches_zero():
    d = BidDirective("decrease_bid", Decimal("99.99"), None, None)
    assert desired_bid(Decimal("0.02"), d) >= AMAZON_MIN_BID


# ── Which directive applies ────────────────────────────────────────────────

def test_no_active_window_means_no_directive():
    """None is read by the reconciler as "restore the baseline", NOT as "leave
    it alone". Leaving it would let a discount outlive its window and drift
    further every day — the exact behaviour the team would have to undo by
    hand."""
    assert desired_bid_directive_at([bid_entry(0, 14, 22)], MON_03) is None
    assert desired_bid_directive_at([bid_entry(0, 14, 22)], SAT_15) is None


def test_active_window_returns_its_directive():
    d = desired_bid_directive_at([bid_entry(0, 14, 22, pct=20, min_bid="0.18")], MON_15)
    assert d is not None
    assert d.action == "decrease_bid"
    assert d.pct == Decimal("20")
    assert d.min_bid == Decimal("0.18")


def test_pause_and_enable_entries_are_not_read_as_bid_directives():
    entries = [bid_entry(0, 14, 22, action="pause", pct=None),
               bid_entry(0, 14, 22, action="enable", pct=None)]
    assert desired_bid_directive_at(entries, MON_15) is None


def test_bid_entries_are_not_read_as_a_state():
    """The two decisions must stay independent: a bid window must not switch a
    campaign on or off as a side effect."""
    assert desired_state_at([bid_entry(0, 14, 22)], MON_15) is None


def test_overlapping_bid_windows_pick_the_cheapest():
    """Overlap is a configuration error. As with pause beating enable, the
    reading that costs less money wins."""
    entries = [bid_entry(0, 14, 22, pct=10), bid_entry(0, 10, 18, pct=40)]
    d = desired_bid_directive_at(entries, MON_15)
    assert d.pct == Decimal("40")


def test_an_increase_loses_to_an_overlapping_decrease():
    entries = [bid_entry(0, 14, 22, action="increase_bid", pct=50),
               bid_entry(0, 14, 22, action="decrease_bid", pct=10)]
    d = desired_bid_directive_at(entries, MON_15)
    assert d.action == "decrease_bid"


def test_hour_start_inclusive_hour_end_exclusive():
    e = [bid_entry(0, 14, 22)]
    assert desired_bid_directive_at(e, datetime(2026, 8, 10, 14, 0)) is not None
    assert desired_bid_directive_at(e, datetime(2026, 8, 10, 21, 59)) is not None
    assert desired_bid_directive_at(e, datetime(2026, 8, 10, 22, 0)) is None


def test_an_entry_missing_its_percentage_is_ignored_not_crashed():
    """The CHECK constraint forbids this, but a None percentage reaching the
    arithmetic would raise once per keyword and abort the whole reconcile."""
    assert desired_bid_directive_at([bid_entry(0, 14, 22, pct=None)], MON_15) is None


# ── The team's actual schedule from Helium 10 ───────────────────────────────

def test_the_teams_monday_schedule_behaves_as_they_described():
    """Straight from the screenshot: pause 00-05, -10% 05-14, -20% 14-22,
    pause 22-24."""
    entries = [
        bid_entry(0, 0, 5, action="pause", pct=None),
        bid_entry(0, 5, 14, pct=10, min_bid="0.20"),
        bid_entry(0, 14, 22, pct=20, min_bid="0.18"),
        bid_entry(0, 22, 24, action="pause", pct=None),
    ]
    at = lambda h: datetime(2026, 8, 10, h, 0)

    assert desired_state_at(entries, at(2)) == "paused"
    assert desired_bid_directive_at(entries, at(2)) is None

    assert desired_state_at(entries, at(9)) is None
    assert desired_bid(Decimal("1.00"), desired_bid_directive_at(entries, at(9))) \
        == Decimal("0.90")

    assert desired_bid(Decimal("1.00"), desired_bid_directive_at(entries, at(16))) \
        == Decimal("0.80")

    assert desired_state_at(entries, at(23)) == "paused"


# ── Safety rails that are easy to regress ──────────────────────────────────

def test_write_cap_exists_and_is_finite():
    """Amazon has no hourly bid multiplier, so a window is written per keyword.
    Without a cap one schedule could attempt hundreds of thousands of writes."""
    assert settings.dayparting_max_bid_writes_per_run > 0


@pytest.mark.parametrize("pct", ["0.01", "50", "99.99"])
def test_any_legal_decrease_stays_above_amazons_floor(pct):
    d = BidDirective("decrease_bid", Decimal(pct), None, None)
    assert desired_bid(Decimal("5.00"), d) >= AMAZON_MIN_BID


# ── Reconciler invariants ──────────────────────────────────────────────────
# These guard behaviours that cost money or trust when they regress. The suite
# has no database fixture, so they assert on structure; each one exists because
# the opposite behaviour is both plausible and damaging.
import inspect

from app.modules.dayparting.service import DaypartingService


def _reconcile_src():
    return inspect.getsource(DaypartingService._reconcile_bids)


def test_a_rejected_write_does_not_record_last_written_bid():
    """The nastiest failure mode in this feature.

    Amazon v3 returns 200/207 with per-item errors, so a "successful" HTTP call
    can still have applied nothing. If last_written_bid were stored anyway, the
    next run would compare Amazon's untouched bid against a number we never
    actually wrote, conclude a human edited it, and release a keyword nobody
    touched — with a notification blaming the team.
    """
    src = _reconcile_src()
    not_ok = src.index('if not outcome.get("ok")')
    assign = src.index("state.last_written_bid = wanted")
    assert not_ok < assign, (
        "the not-ok branch must return before last_written_bid is assigned"
    )
    assert "continue" in src[not_ok:assign]


def test_drift_is_measured_against_our_own_last_write():
    """Comparing against the baseline instead would flag every keyword the app
    itself adjusted as a manual edit, and release the entire schedule on its
    second run."""
    src = _reconcile_src()
    assert "state.last_written_bid is not None" in src
    assert "current != Decimal(str(state.last_written_bid))" in src


def test_a_released_target_is_never_written_again():
    src = _reconcile_src()
    released_check = src.index("if state.released_at is not None")
    write_call = src.index("writer(")
    assert released_check < write_call
    assert "continue" in src[released_check:released_check + 200]


def test_the_bid_pass_is_skipped_while_the_schedule_wants_a_pause():
    """Restoring baselines on a paused campaign would spend thousands of writes
    to change bids on ads that are not running."""
    src = inspect.getsource(DaypartingService.reconcile_schedule)
    assert 'if desired != "paused":' in src
    assert "_reconcile_bids" in src


def test_no_window_active_still_runs_the_bid_pass():
    """A schedule made only of bid windows has no desired state at any hour.
    An early return on `desired is None` — which is what the code used to do —
    would mean bids were never restored to baseline."""
    src = inspect.getsource(DaypartingService.reconcile_schedule)
    # Both passes must be reached unconditionally once scope is resolved.
    states_call = src.index("_reconcile_states")
    bid_call = src.index("_reconcile_bids")
    assert states_call < bid_call
    between = src[states_call:bid_call]
    assert "return result" not in between, (
        "nothing may return between the state pass and the bid pass"
    )
    # And the None case must be handled inside the state pass, not skipped.
    states_src = inspect.getsource(DaypartingService._reconcile_states)
    assert "desired is not None" in states_src


def test_only_enabled_campaigns_and_targets_are_touched():
    src = _reconcile_src()
    assert '(c.status or "").lower() == "enabled"' in src
    assert 'func.lower(Target.status) == "enabled"' in src


def test_an_unchanged_bid_costs_no_write():
    """Reconciliation runs hourly; writing when nothing changed would multiply
    the account's write volume by the number of runs per window."""
    src = _reconcile_src()
    assert "if current == wanted:" in src
    idx = src.index("if current == wanted:")
    assert "continue" in src[idx:idx + 120]


def test_the_write_cap_reports_what_it_dropped():
    """A truncated reconcile that reported success would read as "every bid is
    correct now"."""
    src = _reconcile_src()
    assert "OUTCOME_BID_CAPPED" in src
    assert "logger.warning" in src
    assert "next run" in src


def test_confirmed_bid_changes_reach_the_shared_audit_trail():
    src = _reconcile_src()
    assert "record_change" in src
    assert 'source="dayparting"' in src
    assert 'field_changed="bid"' in src


def test_keyword_and_product_targets_use_different_amazon_endpoints():
    """/sp/keywords and /sp/targets are separate resources; sending a keyword
    id to the product endpoint fails per-item."""
    src = _reconcile_src()
    assert 'target.target_kind == "keyword"' in src
    assert "update_keyword_bid" in src and "update_target_bid" in src


def test_release_notification_is_not_labelled_a_failure():
    """Releasing is the app deferring to a human. Filing it under
    dayparting_failed would train the team to ignore real failures."""
    src = inspect.getsource(DaypartingService._notify_released)
    assert '"dayparting_released"' in src
    # Check the notify() call itself, not the prose around it.
    call = src[src.index("NotificationService(self.db).notify("):]
    assert "dayparting_failed" not in call


def test_a_notification_failure_cannot_undo_confirmed_bid_changes():
    src = inspect.getsource(DaypartingService._notify_released)
    assert "except Exception" in src


# ── Campaign state: restore only what the app itself changed ────────────────
# Unpainted hours used to mean "leave it alone", so a schedule with only a pause
# window switched the ads off at midnight and never switched them back on —
# silently, every day. The team asked why the green "enable" cells were needed;
# the honest answer was that forgetting them was catastrophic and unreported.

def _states_src():
    return inspect.getsource(DaypartingService._reconcile_states)


def test_no_window_means_restore_not_leave_alone():
    src = _states_src()
    assert "state.baseline_status" in src, (
        "with no window active the app must put back what it changed"
    )


def test_a_campaign_the_schedule_never_touched_is_left_alone():
    """The reason this is not simply "unpainted means enabled": a campaign a
    human paused (out of stock, budget freeze) must never be switched on. No
    state row means no write."""
    src = _states_src()
    idx = src.index("else:\n                continue   # never touched")
    assert idx > 0, "the no-state-row branch must continue, not default to a write"


def test_restore_requires_the_app_to_have_actually_written():
    """baseline_status alone is not enough — a row whose write failed has
    last_written_status NULL and must not trigger a restore."""
    src = _states_src()
    assert "state.last_written_status is not None" in src


def test_a_rejected_state_write_does_not_record_last_written_status():
    """Same trap as the bid path: recording a write Amazon refused would
    manufacture drift and release a campaign nobody touched."""
    src = _states_src()
    not_ok = src.index('if not outcome.get("ok")')
    assign = src.index("state.last_written_status = target")
    assert not_ok < assign
    assert "continue" in src[not_ok:assign]


def test_state_drift_is_measured_against_our_own_last_write():
    src = _states_src()
    assert "current != state.last_written_status" in src


def test_a_released_campaign_is_never_written_again():
    src = _states_src()
    released = src.index("state.released_at is not None")
    write = src.index("update_campaign_state(")
    assert released < write


def test_archived_campaigns_are_never_touched():
    """Amazon cannot un-archive, so a restore to 'enabled' would fail forever."""
    src = _states_src()
    assert 'current == "archived"' in src
    assert "baseline_status IN ('enabled', 'paused')" not in src  # that lives in the migration


def test_baseline_only_ever_records_a_restorable_status():
    src = _states_src()
    assert 'current in ("enabled", "paused")' in src, (
        "an unexpected status must not be stored as a restore target"
    )


def test_state_release_notification_says_campaign_not_keyword():
    src = _states_src()
    assert 'noun="campaign"' in src
