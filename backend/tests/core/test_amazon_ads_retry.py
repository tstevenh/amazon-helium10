"""A transient connection error mid-pagination must be retried, not fatal."""
import pytest
from requests.exceptions import ConnectionError as ReqConnectionError

from app.core import amazon_ads
from app.core.amazon_ads import PartialFetchError


def test_transient_connection_error_is_retried_and_succeeds(fake_requests):
    """First attempt drops; retry succeeds. The fetch must complete normally."""
    fake_requests.queue_exception("POST", "/sp/campaigns/list", ReqConnectionError("Remote end closed"))
    fake_requests.queue_response(
        "POST", "/sp/campaigns/list", 200,
        {"campaigns": [{"campaignId": "5", "name": "C", "state": "ENABLED",
                        "budget": {"budget": 1.0}, "targetingType": "MANUAL"}]},
    )
    fake_requests.queue_response("POST", "/sb/v4/campaigns/list", 200, {"campaigns": []})

    result = amazon_ads.list_campaigns("tok", 123)

    assert len(result) == 1, "retry should have recovered the fetch"


def test_retries_are_bounded_then_raise(fake_requests):
    """Persistent failure must eventually give up — not loop forever."""
    for _ in range(10):
        fake_requests.queue_exception("POST", "/sp/campaigns/list", ReqConnectionError("down"))
    fake_requests.queue_response("POST", "/sb/v4/campaigns/list", 200, {"campaigns": []})

    with pytest.raises(PartialFetchError):
        amazon_ads.list_campaigns("tok", 123)

    sp_calls = [c for c in fake_requests.calls if "/sp/campaigns/list" in c[1]]
    assert 2 <= len(sp_calls) <= 6, f"expected bounded retries, saw {len(sp_calls)}"


def test_http_4xx_is_not_retried(fake_requests):
    """A 401/403 will never succeed on retry — fail fast, don't hammer Amazon."""
    fake_requests.queue_response("POST", "/sp/campaigns/list", 403, {"code": "FORBIDDEN", "details": "no"})
    fake_requests.queue_response("POST", "/sb/v4/campaigns/list", 200, {"campaigns": []})

    with pytest.raises(PartialFetchError):
        amazon_ads.list_campaigns("tok", 123)

    sp_calls = [c for c in fake_requests.calls if "/sp/campaigns/list" in c[1]]
    assert len(sp_calls) == 1, "4xx must not be retried"


def test_http_502_is_retried(fake_requests):
    """The CA profile's intermittent 502 should recover on retry."""
    fake_requests.queue_response("POST", "/sp/campaigns/list", 502, {"code": "E", "details": "bad gateway"})
    fake_requests.queue_response(
        "POST", "/sp/campaigns/list", 200,
        {"campaigns": [{"campaignId": "9", "name": "CA", "state": "ENABLED",
                        "budget": {"budget": 2.0}, "targetingType": "MANUAL"}]},
    )
    fake_requests.queue_response("POST", "/sb/v4/campaigns/list", 200, {"campaigns": []})

    result = amazon_ads.list_campaigns("tok", 123)

    assert len(result) == 1, "5xx should be retried and recover"
