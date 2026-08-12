"""Budget rules: units, guards, and the compounding problem.

The unit test at the top of this file exists because of a real bug. Rule rows
carry ACoS as a RATIO, because _field_value multiplies percent fields by 100 to
compare against the operator's "40" meaning 40%. SearchTermRepository returns a
ratio. PerformanceRepository returns a PERCENTAGE for acos while returning a
ratio for ctr — inconsistent inside one function.

Feeding the percentage straight through made "ACoS > 40" evaluate as
"ACoS > 0.4%", which matched a campaign running at 24% real ACoS. That is not a
cosmetic error: it proposed cutting the budget of a profitable campaign.
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.rules.service import RuleEngine, _field_value


class _Rule:
    """Minimal stand-in for a budget Rule."""
    def __init__(self, **cfg):
        self.id = "rule-1"
        self.name = "test budget rule"
        self.rule_type = "budget"
        self.profile_id = "profile-1"
        self.configuration_json = cfg


def test_percent_fields_are_stored_as_ratios_in_rule_rows():
    """The engine's contract: 0.577 in the row means 57.7% to the operator."""
    assert _field_value({"acos": 0.577}, "acos") == pytest.approx(57.7, abs=0.01)
    assert _field_value({"ctr": 0.02}, "ctr") == pytest.approx(2.0)
    assert _field_value({"conversion_rate": 0.15}, "conversion_rate") == pytest.approx(15.0)


def test_a_percentage_fed_in_as_a_ratio_is_off_by_100x():
    """Documents the exact failure, so nobody 'simplifies' the conversion away.

    A campaign at 57.7% ACoS whose value is passed through as 57.7 reads as
    5770% — and every threshold comparison becomes meaningless.
    """
    correct = _field_value({"acos": 0.577}, "acos")
    wrong = _field_value({"acos": 57.7}, "acos")

    assert correct == pytest.approx(57.7, abs=0.01)
    assert wrong == pytest.approx(5770.0, abs=1)
    # The consequence: a "> 40" rule fires on a 0.4% ACoS campaign.
    assert _field_value({"acos": 0.004}, "acos") < 40      # correct: no match
    assert _field_value({"acos": 0.4}, "acos") == pytest.approx(40.0)


def test_budget_conversion_happens_in_campaign_rows():
    """Guards the fix itself, not just the helper it feeds."""
    import inspect

    src = inspect.getsource(RuleEngine._campaign_rows)
    assert '"acos"' in src
    assert "/ 100" in src, (
        "PerformanceRepository returns acos as a percentage; _campaign_rows "
        "must divide by 100 to match the ratio convention rule rows use"
    )


# ── The new-campaign grace window ──────────────────────────────────────────

def test_grace_window_matches_amazons_processing_delay():
    """Spec, verified from Adtomic: skip campaigns under 3 days old."""
    assert RuleEngine._NEW_CAMPAIGN_GRACE_DAYS == 3


def test_budget_types_are_exactly_increase_and_decrease():
    assert RuleEngine._BUDGET_TYPES == {"budget_increase", "budget_decrease"}


# ── Budget arithmetic ──────────────────────────────────────────────────────

def _resolve(current_budget, sugg_type, percent):
    engine = RuleEngine.__new__(RuleEngine)      # no DB needed
    campaign = SimpleNamespace(daily_budget=Decimal(str(current_budget)))
    return engine._resolve_budget_change(
        {"_campaign": campaign}, sugg_type, {"percent": percent},
    )


def test_decrease_applies_the_percentage():
    _, current, new = _resolve(10.00, "budget_decrease", 20)
    assert current == 10.00
    assert new == 8.00


def test_increase_applies_the_percentage():
    _, current, new = _resolve(10.00, "budget_increase", 20)
    assert new == 12.00


def test_a_cut_below_amazons_one_dollar_floor_is_skipped():
    """Amazon rejects a daily budget under $1.00.

    Skipping beats creating a suggestion that is guaranteed to fail on
    execution — a failed suggestion in the inbox looks like a broken app.
    """
    assert _resolve(1.10, "budget_decrease", 20) is None      # would be $0.88


def test_a_cut_that_lands_exactly_on_the_floor_is_allowed():
    _, _, new = _resolve(1.25, "budget_decrease", 20)
    assert new == 1.00


def test_a_change_too_small_to_matter_is_skipped():
    """Sub-cent moves are inbox noise, not decisions."""
    assert _resolve(1.00, "budget_decrease", 0.1) is None


def test_a_campaign_with_no_budget_is_skipped():
    engine = RuleEngine.__new__(RuleEngine)
    campaign = SimpleNamespace(daily_budget=None)
    assert engine._resolve_budget_change(
        {"_campaign": campaign}, "budget_decrease", {"percent": 20}) is None


def test_non_budget_suggestion_types_are_ignored():
    """Belt and braces: this resolver must never act on a bid suggestion."""
    assert _resolve(10.00, "bid_decrease", 20) is None
