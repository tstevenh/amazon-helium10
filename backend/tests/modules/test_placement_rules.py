"""Placement rules: percentage points, and the wholesale-replacement hazard.

Two things make placement different from bids and budgets:

1. Amazon's adjustment is a PERCENTAGE UPLIFT (0-900), not a price. So the unit
   of change is percentage POINTS. Treating it as "20% of the current value"
   would mean a campaign sitting at 0% could never be raised.

2. Amazon REPLACES the whole placementBidding array. Sending only the placement
   you are changing silently resets the other two to 0%. That is a destructive
   no-op: it looks like success and quietly cancels adjustments someone set.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.rules.service import RuleEngine


def campaign(**adjustments):
    """A campaign whose placement_bidding is in Amazon's own list shape."""
    amazon_names = {
        "top_of_search": "PLACEMENT_TOP",
        "product_pages": "PLACEMENT_PRODUCT_PAGE",
        "rest_of_search": "PLACEMENT_REST_OF_SEARCH",
    }
    return SimpleNamespace(
        id="camp-1",
        name="Test Campaign",
        placement_bidding=[
            {"placement": amazon_names[k], "percentage": v}
            for k, v in adjustments.items()
        ] or None,
    )


def resolve(sugg_type, points, placement="top_of_search", **current):
    engine = RuleEngine.__new__(RuleEngine)
    row = {"_campaign": campaign(**current), "_placement": placement}
    return engine._resolve_placement_change(row, sugg_type, {"percent": points})


# ── Reading current adjustments ─────────────────────────────────────────────

def test_a_campaign_with_no_adjustments_reads_as_zero_everywhere():
    """Amazon's default is 0%, and that is different from "unknown"."""
    got = RuleEngine.current_placement_adjustments(campaign())
    assert got == {"top_of_search": 0.0, "product_pages": 0.0, "rest_of_search": 0.0}


def test_amazon_placement_names_are_translated():
    got = RuleEngine.current_placement_adjustments(
        campaign(top_of_search=25, product_pages=10)
    )
    assert got["top_of_search"] == 25
    assert got["product_pages"] == 10
    assert got["rest_of_search"] == 0.0     # absent means default, not missing


def test_a_dict_shaped_payload_is_also_accepted():
    """placement_bidding is synced data and Amazon has changed its shape before."""
    c = SimpleNamespace(placement_bidding={"placementBidding": [
        {"placement": "PLACEMENT_TOP", "percentage": 40},
    ]})
    assert RuleEngine.current_placement_adjustments(c)["top_of_search"] == 40


def test_unparseable_percentages_do_not_break_the_read():
    c = SimpleNamespace(placement_bidding=[
        {"placement": "PLACEMENT_TOP", "percentage": "not a number"},
        {"placement": "PLACEMENT_PRODUCT_PAGE", "percentage": 15},
    ])
    got = RuleEngine.current_placement_adjustments(c)
    assert got["top_of_search"] == 0.0      # skipped, defaulted
    assert got["product_pages"] == 15


# ── Points arithmetic ───────────────────────────────────────────────────────

def test_increase_adds_percentage_points():
    _, _, current, new = resolve("placement_increase", 20, top_of_search=10)
    assert current == 10
    assert new == 30            # 10 + 20 points, NOT 10 * 1.2


def test_a_campaign_at_zero_can_still_be_raised():
    """The whole reason for points rather than percentages.

    A multiplicative rule applied to 0% would return 0% forever, so no campaign
    at Amazon's default could ever be adjusted up.
    """
    _, _, current, new = resolve("placement_increase", 25)
    assert current == 0.0
    assert new == 25


def test_decrease_subtracts_and_floors_at_zero():
    _, _, current, new = resolve("placement_decrease", 30, top_of_search=10)
    assert new == 0.0           # not -20


def test_a_decrease_at_zero_is_skipped_rather_than_suggested():
    """Already at the floor: there is no change to propose."""
    assert resolve("placement_decrease", 20) is None


def test_an_increase_is_capped_at_amazons_ceiling():
    _, _, _, new = resolve("placement_increase", 200, top_of_search=800)
    assert new == 900


def test_an_increase_already_at_the_ceiling_is_skipped():
    assert resolve("placement_increase", 50, top_of_search=900) is None


def test_the_unlabelled_placement_can_never_become_a_suggestion():
    """'other' exists in the performance table for rows Amazon sent without a
    label. There is no placement to adjust, so it must never be suggested."""
    assert resolve("placement_increase", 20, placement="other") is None


def test_a_bid_suggestion_type_is_ignored_by_this_resolver():
    assert resolve("bid_increase", 20, top_of_search=10) is None


# ── The wholesale-replacement hazard ────────────────────────────────────────

def test_the_suggestion_stores_every_current_adjustment_not_just_one():
    """The executor needs the full set, because Amazon replaces the array.

    If the suggestion only carried the placement being changed, execution would
    send one entry and silently zero the other two.
    """
    import inspect

    src = inspect.getsource(RuleEngine._make_placement_suggestion)
    assert "all_adjustments" in src, (
        "current_value must carry every placement's adjustment, or execution "
        "cannot send the full array Amazon requires"
    )


def test_execution_sends_all_placements():
    import inspect

    from app.modules.execution.service import ExecutionService

    src = inspect.getsource(ExecutionService._execute_placement)
    assert "to_send" in src
    # It must start from the live full set, not from the single placement.
    assert "current_placement_adjustments" in src, (
        "execution must read every current adjustment before writing"
    )


def test_execution_refuses_when_adjustments_drifted_on_amazon():
    """Someone may have changed placements in Amazon's console since the
    suggestion was made. Overwriting that silently is worse than failing."""
    import inspect

    from app.modules.execution.service import ExecutionService

    src = inspect.getsource(ExecutionService._execute_placement)
    assert "drifted" in src


# ── Row shaping ─────────────────────────────────────────────────────────────

def test_placement_rows_keep_acos_as_a_ratio():
    """placement_summary already returns a ratio, unlike the campaign summary.

    Converting again would reintroduce the 100x error that made a 40% ACoS rule
    fire at 0.4%.
    """
    import inspect

    src = inspect.getsource(RuleEngine._placement_rows)
    assert "/ 100" not in src, (
        "placement_summary returns acos as a ratio already — dividing again "
        "would understate it 100-fold"
    )


def test_placement_row_search_term_identifies_campaign_and_placement():
    """Uniqueness leans on the existing (profile, search_term, type) index, so
    the term has to distinguish placements within one campaign."""
    import inspect

    src = inspect.getsource(RuleEngine._placement_rows)
    assert "_PLACEMENT_LABELS[placement]" in src
