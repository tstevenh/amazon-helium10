"""A capped list must be capped on the rows that matter.

The Keywords screen can only render a couple of thousand of the account's
~219,000 keywords. The original API applied LIMIT with no ORDER BY, so
Postgres returned an arbitrary slice — overwhelmingly zero-traffic keywords —
and the screen read as "this app has no data". Ranking by spend in SQL is
what makes the cap honest, so it is guarded here rather than left to a
reviewer to notice if someone edits the query.
"""
import inspect

from app.modules.performance.repository import PerformanceRepository


def _src(fn) -> str:
    return inspect.getsource(fn)


def test_targets_listing_is_ordered_by_spend_before_limiting():
    src = _src(PerformanceRepository.top_targets_by_spend)
    order_at = src.find("ORDER BY")
    limit_at = src.find("LIMIT")
    assert order_at != -1, "an unordered LIMIT returns an arbitrary slice"
    assert limit_at > order_at, "LIMIT must follow ORDER BY, not replace it"
    assert "SUM(p.spend), 0) DESC" in src, "highest spend must come first"


def test_ad_groups_listing_is_ordered_by_spend_before_limiting():
    src = _src(PerformanceRepository.top_ad_groups_by_spend)
    order_at = src.find("ORDER BY")
    limit_at = src.find("LIMIT")
    assert order_at != -1
    assert limit_at > order_at
    assert "SUM(p.spend), 0) DESC" in src


def test_listings_use_a_left_join_so_zero_spend_rows_still_appear():
    """An INNER JOIN would silently hide every keyword with no report rows.

    Those rows are exactly what a paused-campaign audit needs to see, and
    their absence would look like a sync failure.
    """
    for fn in (PerformanceRepository.top_targets_by_spend,
               PerformanceRepository.top_ad_groups_by_spend):
        src = _src(fn)
        assert "LEFT JOIN target_performance_daily" in src or \
               "LEFT JOIN ad_group_performance_daily" in src


def test_listings_exclude_soft_deleted_rows():
    """Soft-deleted entities are kept for history, never shown as live."""
    for fn in (PerformanceRepository.top_targets_by_spend,
               PerformanceRepository.top_ad_groups_by_spend):
        assert "deleted_at IS NULL" in _src(fn)


def test_date_filter_sits_in_the_join_not_the_where_clause():
    """Moving it to WHERE would turn the LEFT JOIN back into an inner one.

    A row whose only performance records fall outside the window would then
    vanish from the list entirely instead of showing $0.00.
    """
    for fn in (PerformanceRepository.top_targets_by_spend,
               PerformanceRepository.top_ad_groups_by_spend):
        src = _src(fn)
        join_at = src.find("LEFT JOIN")
        where_at = src.find("WHERE")
        date_at = src.find("p.date BETWEEN")
        assert join_at < date_at < where_at, "date filter must be an ON condition"


def test_derived_metrics_are_none_not_zero_when_undefined():
    """A keyword with no clicks has no CPC; $0.00 would read as free clicks."""
    row = {"impressions": 0, "clicks": 0, "spend": 0, "sales": 0, "orders": 0}
    out = PerformanceRepository._derive(row)

    assert out["ctr"] is None
    assert out["cpc"] is None
    assert out["acos"] is None
    assert out["roas"] is None
    assert out["spend"] == 0.0


def test_acos_is_none_when_there_are_no_sales_even_with_spend():
    """ACOS is spend/sales — undefined at zero sales, not 0%.

    Reporting 0% would rank a money-losing keyword as the best performer.
    """
    out = PerformanceRepository._derive(
        {"impressions": 100, "clicks": 5, "spend": 2.11, "sales": 0, "orders": 0}
    )

    assert out["acos"] is None
    assert out["roas"] == 0.0


def test_empty_profile_list_short_circuits():
    """No profiles must mean no rows, never 'every row in the database'."""
    repo = PerformanceRepository.__new__(PerformanceRepository)  # no DB needed
    assert repo.top_targets_by_spend([], None, None) == []
    assert repo.top_ad_groups_by_spend([], None, None) == []
    assert repo.count_targets([]) == 0
