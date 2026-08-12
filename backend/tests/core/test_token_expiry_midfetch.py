"""A token expiring mid-pagination must be refreshed, not fatal.

Observed twice on the live account (2026-08-06 16:27 and 2026-08-07 19:38):
sync_targets fetched one token, then paginated 239 pages over ~5 minutes. A
token with 90 seconds left passes the 60-second refresh buffer, then expires
partway through, and every remaining page returns HTTP 401. The sync recorded
11,128 of 233,512 rows.

The reporting client already refreshes per chunk via token_getter; the list
fetches never did.
"""
import pytest

from app.core import amazon_ads
from app.core.amazon_ads import PartialFetchError


def _kw(kid: int) -> dict:
    return {"keywordId": str(kid), "adGroupId": "500", "matchType": "EXACT",
            "keywordText": f"kw{kid}", "bid": 1.0, "state": "ENABLED"}


def test_401_midway_is_recovered_by_refreshing_the_token(fake_requests):
    """Page 1 succeeds, page 2 401s, the refreshed token makes page 2 work."""
    fake_requests.queue_response("POST", "/sp/keywords/list", 200,
                                 {"keywords": [_kw(1)], "nextToken": "page2"})
    fake_requests.queue_response("POST", "/sp/keywords/list", 401,
                                 {"message": "Unauthorized exception"})
    fake_requests.queue_response("POST", "/sp/keywords/list", 200,
                                 {"keywords": [_kw(2)]})

    refreshes: list[int] = []

    def token_getter() -> str:
        refreshes.append(1)
        return "fresh-token"

    rows, truncated, pages = amazon_ads._post_list_paginated(
        "https://x/sp/keywords/list",
        {"Authorization": "Bearer stale", "Content-Type": "application/json"},
        {"maxResults": 1000},
        "keywords",
        token_getter=token_getter,
    )

    assert len(refreshes) == 1, "must refresh exactly once, not per page"
    assert len(rows) == 2, "both pages must be returned after recovery"


def test_401_without_a_token_getter_still_raises(fake_requests):
    """Callers that cannot refresh must still fail loudly, not silently."""
    fake_requests.queue_response("POST", "/sp/keywords/list", 401,
                                 {"message": "Unauthorized exception"})

    with pytest.raises(Exception):
        amazon_ads._post_list_paginated(
            "https://x/sp/keywords/list",
            {"Authorization": "Bearer stale"},
            {},
            "keywords",
        )


def test_a_second_401_after_refresh_is_not_retried_forever(fake_requests):
    """A genuinely revoked token must fail, not loop."""
    for _ in range(4):
        fake_requests.queue_response("POST", "/sp/keywords/list", 401,
                                     {"message": "Unauthorized exception"})

    with pytest.raises(Exception):
        amazon_ads._post_list_paginated(
            "https://x/sp/keywords/list",
            {"Authorization": "Bearer stale"},
            {},
            "keywords",
            token_getter=lambda: "still-bad",
        )

    calls = [c for c in fake_requests.calls if "keywords/list" in c[1]]
    assert len(calls) <= 3, f"must not retry indefinitely, saw {len(calls)} calls"


def test_refresh_buffer_covers_a_long_paginated_fetch():
    """A 60-second buffer is shorter than the fetch it has to survive.

    The US profile's keyword fetch is 239 pages and takes ~5 minutes, so the
    buffer must exceed that or a token can pass the check and still expire
    mid-fetch.
    """
    from app.modules.accounts import service as acct_service

    assert acct_service._REFRESH_BUFFER_SECONDS >= 300, (
        "refresh buffer must exceed the duration of the longest fetch"
    )
