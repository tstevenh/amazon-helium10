"""The Amazon Search Term report must actually be fetched in real mode.

Before this, search_terms/service.py returned 0 in real mode with a
"not implemented" warning, which silently disabled the Search Terms,
Suggestions and Rules modules.
"""
import inspect
from datetime import date

import pytest

from app.core import amazon_reporting


def test_search_term_metrics_include_date():
    """The bug from 2026-08-03: v3 omits `date` unless explicitly requested."""
    assert "date" in amazon_reporting._SEARCH_TERM_METRICS


def test_search_term_metrics_include_the_search_term_column():
    assert "searchTerm" in amazon_reporting._SEARCH_TERM_METRICS


def test_search_term_metrics_identify_the_owning_ad_group():
    """Rows are keyed by (profile, ad_group, search_term, date) in our schema."""
    assert "adGroupId" in amazon_reporting._SEARCH_TERM_METRICS
    assert "campaignId" in amazon_reporting._SEARCH_TERM_METRICS


def test_fetch_search_term_performance_exists():
    assert hasattr(amazon_reporting, "fetch_search_term_performance")


def test_fetch_normalises_amazon_rows(monkeypatch):
    """Amazon returns strings for IDs and 7-day attribution column names."""
    raw = [
        {
            "date": "2026-08-01",
            "campaignId": "1001",
            "adGroupId": "2001",
            "searchTerm": "Organic Coffee Beans",
            "impressions": "100",
            "clicks": "10",
            "cost": "5.50",
            "purchases7d": "2",
            "sales7d": "40.00",
            "unitsSoldClicks7d": "3",
        }
    ]
    monkeypatch.setattr(
        amazon_reporting, "_fetch_report_chunked",
        lambda *a, **kw: raw,
    )

    rows = amazon_reporting.fetch_search_term_performance(
        "tok", 123, date(2026, 8, 1), date(2026, 8, 2)
    )

    assert len(rows) == 1
    r = rows[0]
    assert r["amazon_campaign_id"] == 1001
    assert r["amazon_ad_group_id"] == 2001
    # Search terms are lowercased so aggregation does not split on casing.
    assert r["search_term"] == "organic coffee beans"
    assert r["date"] == "2026-08-01"
    assert r["impressions"] == 100
    assert r["clicks"] == 10
    assert float(r["cost"]) == 5.50
    assert r["orders"] == 2
    assert float(r["sales"]) == 40.00
    assert r["units"] == 3


def test_rows_without_a_search_term_are_skipped(monkeypatch):
    """search_term is NOT NULL in our schema — a blank row would crash the upsert."""
    raw = [
        {"date": "2026-08-01", "campaignId": "1", "adGroupId": "2", "searchTerm": "",
         "impressions": "5", "clicks": "0", "cost": "0", "purchases7d": "0", "sales7d": "0"},
        {"date": "2026-08-01", "campaignId": "1", "adGroupId": "2", "searchTerm": "ok term",
         "impressions": "5", "clicks": "0", "cost": "0", "purchases7d": "0", "sales7d": "0"},
    ]
    monkeypatch.setattr(amazon_reporting, "_fetch_report_chunked", lambda *a, **kw: raw)

    rows = amazon_reporting.fetch_search_term_performance(
        "tok", 123, date(2026, 8, 1), date(2026, 8, 2)
    )

    assert len(rows) == 1
    assert rows[0]["search_term"] == "ok term"


def test_rows_without_an_ad_group_are_skipped(monkeypatch):
    """Our unique key includes ad_group_id; a row without one cannot be placed."""
    raw = [
        {"date": "2026-08-01", "campaignId": "1", "adGroupId": None, "searchTerm": "x",
         "impressions": "5", "clicks": "0", "cost": "0", "purchases7d": "0", "sales7d": "0"},
    ]
    monkeypatch.setattr(amazon_reporting, "_fetch_report_chunked", lambda *a, **kw: raw)

    rows = amazon_reporting.fetch_search_term_performance(
        "tok", 123, date(2026, 8, 1), date(2026, 8, 2)
    )

    assert rows == []


def test_service_no_longer_short_circuits_in_real_mode():
    """The regression guard: the 'not implemented' early return must be gone."""
    from app.modules.search_terms import service as st_service

    src = inspect.getsource(st_service)
    assert "not implemented" not in src.lower(), (
        "real-mode search term sync must be implemented, not skipped"
    )
    assert "fetch_search_term_performance" in src, "service must call the real fetcher"
