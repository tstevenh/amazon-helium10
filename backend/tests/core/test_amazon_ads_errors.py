"""Phase 0: a failed sub-fetch must raise, never be swallowed into an empty list."""
import pytest

from app.core import amazon_ads
from app.core.amazon_ads import PartialFetchError


def _sp_campaign(cid: int) -> dict:
    return {
        "campaignId": str(cid),
        "name": f"Campaign {cid}",
        "state": "ENABLED",
        "targetingType": "MANUAL",
        "budget": {"budget": 10.0},
        "startDate": "2026-01-01",
    }


def test_list_campaigns_returns_plain_list_when_all_sources_succeed(fake_requests):
    fake_requests.queue_response("POST", "/sp/campaigns/list", 200, {"campaigns": [_sp_campaign(1)]})
    fake_requests.queue_response("POST", "/sb/v4/campaigns/list", 200, {"campaigns": []})

    result = amazon_ads.list_campaigns("tok", 123)

    assert len(result) == 1
    assert result[0]["amazon_campaign_id"] == 1


def test_list_campaigns_raises_when_sp_fetch_fails(fake_requests):
    """The old behaviour logged a warning and returned []. That is the bug."""
    fake_requests.queue_response("POST", "/sp/campaigns/list", 502, {"code": "SERVER_ERROR", "details": "boom"})
    fake_requests.queue_response("POST", "/sb/v4/campaigns/list", 200, {"campaigns": []})

    with pytest.raises(PartialFetchError) as excinfo:
        amazon_ads.list_campaigns("tok", 123)

    assert "SP campaigns" in str(excinfo.value)
    assert excinfo.value.failures, "failures must describe what went wrong"


def test_partial_fetch_error_preserves_successful_items(fake_requests):
    """SB succeeded, SP failed — the SB rows must not be thrown away."""
    fake_requests.queue_response("POST", "/sp/campaigns/list", 500, {"code": "X", "details": "y"})
    fake_requests.queue_response(
        "POST", "/sb/v4/campaigns/list", 200,
        {"campaigns": [{"campaignId": "77", "name": "SB", "state": "ENABLED", "budget": 5.0}]},
    )

    with pytest.raises(PartialFetchError) as excinfo:
        amazon_ads.list_campaigns("tok", 123)

    assert len(excinfo.value.items) == 1
    assert excinfo.value.items[0]["amazon_campaign_id"] == 77
    assert excinfo.value.items[0]["ad_product"] == "SB"


def test_connection_drop_mid_fetch_raises(fake_requests):
    """This is the bug that silently lost 215,000 keywords."""
    from requests.exceptions import ConnectionError as ReqConnectionError

    fake_requests.queue_exception("POST", "/sp/campaigns/list", ReqConnectionError("Remote end closed connection"))
    fake_requests.queue_response("POST", "/sb/v4/campaigns/list", 200, {"campaigns": []})

    with pytest.raises(PartialFetchError):
        amazon_ads.list_campaigns("tok", 123)


def test_list_ad_groups_raises_when_sp_fails(fake_requests):
    fake_requests.queue_response("POST", "/sp/adGroups/list", 502, {"code": "E", "details": "d"})
    fake_requests.queue_response("POST", "/sb/v4/adGroups/list", 200, {"adGroups": []})

    with pytest.raises(PartialFetchError):
        amazon_ads.list_ad_groups("tok", 123)


def test_list_targets_raises_and_keeps_partial_keywords(fake_requests):
    """The 215k-keyword-loss regression test.

    SP keywords dies on a dropped connection; SB keywords succeed. The caller
    must be told, and must still receive the SB rows.
    """
    from requests.exceptions import ConnectionError as ReqConnectionError

    fake_requests.queue_exception("POST", "/sp/keywords/list", ReqConnectionError("Remote end closed connection"))
    fake_requests.queue_response("POST", "/sp/targets/list", 200, {"targetingClauses": []})
    fake_requests.queue_response(
        "GET", "/sb/keywords", 200,
        [{"keywordId": "9001", "adGroupId": "500", "matchType": "EXACT",
          "keywordText": "mug", "bid": 1.0, "state": "ENABLED"}],
    )

    with pytest.raises(PartialFetchError) as excinfo:
        amazon_ads.list_targets("tok", 123)

    assert any("SP keywords" in f for f in excinfo.value.failures)
    assert len(excinfo.value.items) == 1
    assert excinfo.value.items[0]["amazon_target_id"] == 9001


def test_list_targets_succeeds_quietly_when_all_sources_ok(fake_requests):
    fake_requests.queue_response("POST", "/sp/keywords/list", 200, {"keywords": []})
    fake_requests.queue_response("POST", "/sp/targets/list", 200, {"targetingClauses": []})
    fake_requests.queue_response("GET", "/sb/keywords", 200, [])

    targets, truncated, pages, rows = amazon_ads.list_targets("tok", 123)

    assert targets == []
    assert truncated is False
    assert rows == 0
