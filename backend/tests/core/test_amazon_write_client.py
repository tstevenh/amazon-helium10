"""The write client must report per-item outcomes, not just HTTP status.

Amazon's v3 mutation endpoints return 200/207 even when the change was
rejected, with the real outcome buried in a per-item error array. Trusting the
status code would record bid changes that never happened — the same class of
silent failure that cost the team a month on the read path.
"""
import pytest

from app.config import settings
from app.core import amazon_ads_write as w
from app.core.amazon_ads_write import AmazonWriteDisabled


@pytest.fixture
def writes_enabled(monkeypatch):
    monkeypatch.setattr(settings, "amazon_write_enabled", True)


def test_update_keyword_bid_sends_the_new_bid(fake_requests, writes_enabled):
    fake_requests.queue_response(
        "PUT", "/sp/keywords", 207,
        {"keywords": {"success": [{"index": 0, "keywordId": "3001"}], "error": []}},
    )

    result = w.update_keyword_bid("tok", 123, 3001, 0.80)

    assert result["ok"] is True
    assert result["request"]["keywords"][0]["keywordId"] == "3001"
    assert result["request"]["keywords"][0]["bid"] == 0.80


def test_per_item_error_is_a_failure_even_on_http_200(fake_requests, writes_enabled):
    """The critical case: HTTP says 207, the item says BID_TOO_LOW."""
    fake_requests.queue_response(
        "PUT", "/sp/keywords", 207,
        {"keywords": {"success": [],
                      "error": [{"index": 0, "errors": [{"errorType": "BID_TOO_LOW"}]}]}},
    )

    result = w.update_keyword_bid("tok", 123, 3001, 0.01)

    assert result["ok"] is False, "a rejected item must not be reported as success"
    assert "BID_TOO_LOW" in str(result["response"])


def test_empty_success_array_is_a_failure(fake_requests, writes_enabled):
    """No success and no error is still not a confirmed change."""
    fake_requests.queue_response("PUT", "/sp/keywords", 200,
                                 {"keywords": {"success": [], "error": []}})

    assert w.update_keyword_bid("tok", 123, 3001, 0.80)["ok"] is False


def test_http_error_is_a_failure(fake_requests, writes_enabled):
    fake_requests.queue_response("PUT", "/sp/keywords", 403, {"code": "FORBIDDEN"})

    result = w.update_keyword_bid("tok", 123, 3001, 0.80)

    assert result["ok"] is False
    assert result["status_code"] == 403


def test_kill_switch_blocks_before_any_request(fake_requests, monkeypatch):
    """With writes disabled, no HTTP call may be attempted at all."""
    monkeypatch.setattr(settings, "amazon_write_enabled", False)

    with pytest.raises(AmazonWriteDisabled):
        w.update_keyword_bid("tok", 123, 3001, 0.80)

    assert fake_requests.calls == [], "no request may be made while disabled"


def test_update_target_bid(fake_requests, writes_enabled):
    fake_requests.queue_response(
        "PUT", "/sp/targets", 207,
        {"targetingClauses": {"success": [{"index": 0, "targetId": "9001"}], "error": []}},
    )

    result = w.update_target_bid("tok", 123, 9001, 1.25)

    assert result["ok"] is True
    assert result["request"]["targetingClauses"][0]["bid"] == 1.25


def test_negative_keyword_creation(fake_requests, writes_enabled):
    fake_requests.queue_response(
        "POST", "/sp/negativeKeywords", 207,
        {"negativeKeywords": {"success": [{"index": 0, "negativeKeywordId": "77"}],
                              "error": []}},
    )

    result = w.create_negative_keyword("tok", 123, 2001, 1001, "coffee table", "exact")

    body = result["request"]["negativeKeywords"][0]
    assert result["ok"] is True
    assert body["keywordText"] == "coffee table"
    assert body["matchType"] == "NEGATIVE_EXACT"
    assert body["campaignId"] == "1001"
    assert body["adGroupId"] == "2001"


def test_negative_match_type_is_not_double_prefixed(fake_requests, writes_enabled):
    """Callers may pass 'exact' or 'negative_exact'; both must yield one prefix."""
    for supplied in ("exact", "NEGATIVE_EXACT", "negative_exact"):
        fake_requests.queue_response(
            "POST", "/sp/negativeKeywords", 207,
            {"negativeKeywords": {"success": [{"index": 0}], "error": []}},
        )
        result = w.create_negative_keyword("tok", 123, 2001, 1001, "x", supplied)
        assert result["request"]["negativeKeywords"][0]["matchType"] == "NEGATIVE_EXACT"


def test_bid_is_rejected_if_not_positive(writes_enabled):
    """A zero or negative bid is a programming error, not an Amazon error —
    catch it before it reaches the account."""
    for bad in (0, -1, -0.5, None):
        with pytest.raises(ValueError):
            w.update_keyword_bid("tok", 123, 3001, bad)


def test_bid_validation_happens_before_any_request(fake_requests, writes_enabled):
    with pytest.raises(ValueError):
        w.update_keyword_bid("tok", 123, 3001, 0)

    assert fake_requests.calls == []


def test_write_client_cannot_create_campaigns():
    """Team constraint: the test campaign is created by a human in Amazon's
    console. The code's write surface must stay at three endpoints."""
    import inspect

    src = inspect.getsource(w)
    for forbidden in ("/sp/campaigns", "/sp/adGroups", "/sp/productAds"):
        assert forbidden not in src, f"write client must not touch {forbidden}"
