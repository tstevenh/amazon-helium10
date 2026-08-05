"""
Thin HTTP client for the Amazon Advertising API.

All network calls are centralised here. The rest of the codebase never imports
`requests` directly — it calls the functions below.

Mock mode
---------
When AMAZON_MOCK_MODE=true (env var), every function returns realistic dummy
data instead of hitting Amazon's servers. Mock mode does NOT alter any
production code paths — same functions, same signatures, same return shapes;
only the HTTP calls are skipped.

All functions return NORMALISED dicts with our field names, not raw Amazon field
names. The real-API paths normalise before returning; mock data is already in
normalised form.

Error handling (real mode)
--------------------------
When Amazon returns a 4xx/5xx response, _parse_amazon_error() extracts the
`error` and `error_description` fields from the JSON body and raises
AmazonApiError with a human-readable message. Callers catch AmazonApiError to
surface readable errors instead of generic 500s.

Known Amazon error codes:
  invalid_client         — wrong CLIENT_ID or CLIENT_SECRET
  invalid_grant          — expired/already-used auth code or refresh token
  redirect_uri_mismatch  — redirect URI not registered in LWA app
  access_denied          — user denied consent or missing scope
  invalid_scope          — scope not allowed for this LWA app
  insufficient_scope     — token lacks required scope for Ads API call

API version (Sprint 5)
-----------------------
Sponsored Products (SP): v3 API
  POST /sp/campaigns/list     Content-Type: application/vnd.spCampaign.v3+json
  POST /sp/adGroups/list      Content-Type: application/vnd.spAdGroup.v3+json
  POST /sp/keywords/list      Content-Type: application/vnd.spKeyword.v3+json
  POST /sp/targets/list       Content-Type: application/vnd.spTargetingClause.v3+json

Sponsored Brands (SB): v4 API (campaigns + ad groups) / v3.2 GET (keywords)
  POST /sb/v4/campaigns/list  Content-Type: application/vnd.sbCampaignResource.v4+json
  POST /sb/v4/adGroups/list   Content-Type: application/vnd.sbAdGroupResource.v4+json
  GET  /sb/keywords            Accept: application/vnd.sbkeyword.v3.2+json  (offset pagination)
  NOTE: /sb/v4/keywords/list does NOT exist — Amazon returns 403 with a misleading
        "Invalid key=value pair in Authorization header" error for unknown SB endpoints.

v3/v4 response changes vs v2:
  - IDs are returned as strings (we cast to int for BigInteger columns)
  - States are uppercase ("ENABLED", "PAUSED", "ARCHIVED") — _safe_status handles this
  - Budget: budget.budget (not dailyBudget)
  - Bids: bid.bid / defaultBid.bid (not flat float)
  - SP bidding strategy: dynamicBidding.strategy (not bidding.strategy)
  - Dates: ISO "YYYY-MM-DD" (v2 used "YYYYMMDD")
  - Pagination: nextToken cursor in response body

Status normalisation
--------------------
Amazon API `state` field values are normalised to lowercase and mapped to our
allowed DB values (enabled / paused / archived). Unknown states are mapped to
'paused' as a safe fallback. targeting_type values outside ('manual', 'auto')
are stored as NULL.
"""
import logging
import time
import urllib.parse
from typing import Any

import requests

from app.config import settings

logger = logging.getLogger(__name__)

# Transport-level failures worth retrying. Amazon closes long-running
# connections mid-pagination; a single drop must not discard the whole fetch.
_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """Issue a request, retrying transient failures with exponential backoff.

    Retries on transport errors and on HTTP 429/5xx. Does NOT retry other 4xx
    responses — those never succeed on retry and retrying just hammers Amazon.
    Returns the final response for the caller to run through
    _raise_for_amazon_error(), or re-raises the final transport exception.
    """
    attempts = max(1, settings.amazon_fetch_max_retries)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.request(method, url, **kwargs)
            if (resp.status_code == 429 or resp.status_code >= 500) and attempt < attempts:
                delay = settings.amazon_fetch_backoff_sec * (2 ** (attempt - 1))
                logger.warning(
                    "[amazon_ads] HTTP %d on %s — retry %d/%d in %.1fs",
                    resp.status_code, url, attempt, attempts, delay,
                )
                time.sleep(delay)
                continue
            return resp
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            delay = settings.amazon_fetch_backoff_sec * (2 ** (attempt - 1))
            logger.warning(
                "[amazon_ads] %s on %s — retry %d/%d in %.1fs",
                type(exc).__name__, url, attempt, attempts, delay,
            )
            time.sleep(delay)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"_request_with_retry exhausted without result for {url}")

# Amazon LWA endpoints — stable, not regional.
AMAZON_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
AMAZON_AUTH_BASE_URL = "https://www.amazon.com/ap/oa"

# Human-readable overrides for known Amazon error codes.
_AMAZON_ERROR_MESSAGES: dict[str, str] = {
    "invalid_client": (
        "Amazon rejected the client credentials. "
        "Check AMAZON_CLIENT_ID and AMAZON_CLIENT_SECRET."
    ),
    "invalid_grant": (
        "The authorization code or refresh token is expired or has already been used. "
        "Restart the OAuth flow to get a new code."
    ),
    "redirect_uri_mismatch": (
        "The redirect URI does not match what is registered in your Amazon LWA app. "
        "Register AMAZON_REDIRECT_URI exactly as it appears in your .env."
    ),
    "access_denied": (
        "The user denied authorization or the required scope was not granted."
    ),
    "invalid_scope": (
        "The scope 'advertising::campaign_management' is not enabled for this LWA app. "
        "Check your Amazon Developer Console app settings."
    ),
    "insufficient_scope": (
        "The access token does not have the required scope for this Amazon Ads API call."
    ),
}


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class AmazonApiError(Exception):
    """
    Raised when Amazon returns a non-2xx response with a parseable error body.

    Attributes
    ----------
    amazon_error_code : str
        The raw ``error`` field from Amazon's JSON (e.g. ``"invalid_client"``).
        Empty string if not available.
    http_status : int
        The HTTP status code Amazon returned.
    """

    def __init__(self, message: str, http_status: int = 0, amazon_error_code: str = "") -> None:
        super().__init__(message)
        self.http_status = http_status
        self.amazon_error_code = amazon_error_code

    def __str__(self) -> str:
        return self.args[0]


class PartialFetchError(Exception):
    """Raised when one or more sub-fetches failed but others may have succeeded.

    Carries the rows that WERE retrieved so callers can persist them, plus a
    human-readable description of each failure so the API can surface it.

    Callers MUST NOT run soft-delete logic when this is raised: the item list
    is an incomplete view of Amazon's inventory, and deleting "missing" rows
    would destroy live data.
    """

    def __init__(self, message: str, items: list[dict[str, Any]], failures: list[str]) -> None:
        super().__init__(message)
        self.items = items
        self.failures = failures

    def __str__(self) -> str:
        return self.args[0]


# ---------------------------------------------------------------------------
# Error-parsing helper
# ---------------------------------------------------------------------------

def _parse_amazon_error(resp: requests.Response) -> AmazonApiError:
    """
    Parse an Amazon error response and return an AmazonApiError with a
    human-readable message.

    Amazon error response shape:
      {"error": "invalid_client", "error_description": "..."}
    or v3/v4 shape:
      {"code": "NOT_FOUND", "details": "...", "requestId": "..."}
    """
    http_status = resp.status_code

    # Rate limiting
    if http_status == 429:
        return AmazonApiError(
            "Amazon rate limited the request. Try again in a moment.",
            http_status=429,
            amazon_error_code="rate_limited",
        )

    # Try to parse JSON body
    try:
        body = resp.json()
    except Exception:
        body = {}

    # v3/v4 error shape uses "code" + "details"
    v3_code = body.get("code", "")
    v3_details = body.get("details", "")
    if v3_code and v3_details:
        return AmazonApiError(
            f"HTTP {http_status}: {v3_code}: {v3_details}",
            http_status=http_status,
            amazon_error_code=v3_code,
        )

    # LWA error shape uses "error" + "error_description"
    error_code = body.get("error", "")
    error_desc = body.get("error_description", "")

    if error_code in _AMAZON_ERROR_MESSAGES:
        friendly = _AMAZON_ERROR_MESSAGES[error_code]
        if error_desc and error_desc.lower() not in friendly.lower():
            friendly = f"{friendly} (Amazon says: {error_desc})"
    elif error_code:
        friendly = f"{error_code}: {error_desc}" if error_desc else error_code
    elif error_desc:
        friendly = error_desc
    else:
        friendly = f"HTTP {http_status}: {resp.text[:300]}"

    return AmazonApiError(friendly, http_status=http_status, amazon_error_code=error_code)


def _raise_for_amazon_error(resp: requests.Response) -> None:
    """Raise AmazonApiError if the response is not 2xx."""
    if not resp.ok:
        raise _parse_amazon_error(resp)


# ---------------------------------------------------------------------------
# Status / targeting_type normalisation helpers
# ---------------------------------------------------------------------------

_VALID_STATUSES = frozenset({"enabled", "paused", "archived"})
_VALID_TARGETING_TYPES = frozenset({"manual", "auto"})


def _safe_status(raw_state: Any) -> str:
    """
    Normalise an Amazon campaign/ad group/target state field to one of our
    allowed DB values: enabled | paused | archived.

    v2 returned lowercase ('enabled'); v3/v4 return uppercase ('ENABLED').
    Unknown states are mapped to 'paused' as a safe fallback.
    """
    if not raw_state:
        return "enabled"
    s = str(raw_state).strip().lower()
    return s if s in _VALID_STATUSES else "paused"


def _safe_targeting_type(raw_type: Any) -> str | None:
    """
    Normalise targeting_type to 'manual', 'auto', or NULL.
    v3 returns uppercase 'MANUAL'/'AUTO'; SB may return other values.
    """
    if not raw_type:
        return None
    s = str(raw_type).strip().lower()
    return s if s in _VALID_TARGETING_TYPES else None


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

_MOCK_PROFILES: list[dict[str, Any]] = [
    {
        "profileId": 9999000000001,
        "countryCode": "US",
        "currencyCode": "USD",
        "timezone": "America/Los_Angeles",
        "accountInfo": {
            "marketplaceStringId": "ATVPDKIKX0DER",
            "id": "ENTITY_MOCK_US",
            "type": "seller",
            "name": "Mock Seller US",
        },
    },
    {
        "profileId": 9999000000002,
        "countryCode": "CA",
        "currencyCode": "CAD",
        "timezone": "America/Toronto",
        "accountInfo": {
            "marketplaceStringId": "A2EUQ1WTGCTBG2",
            "id": "ENTITY_MOCK_CA",
            "type": "seller",
            "name": "Mock Seller CA",
        },
    },
]

# Normalised campaigns keyed by amazon_profile_id (int)
_MOCK_CAMPAIGNS: dict[int, list[dict[str, Any]]] = {
    9999000000001: [
        {
            "amazon_campaign_id": 1001,
            "ad_product": "SP",
            "name": "Brand Defense – Exact Match",
            "targeting_type": "manual",
            "status": "enabled",
            "daily_budget": 100.00,
            "start_date": "2024-01-01",
            "end_date": None,
            "bidding_strategy": "LEGACY_FOR_SALES",
        },
        {
            "amazon_campaign_id": 1002,
            "ad_product": "SP",
            "name": "Category Conquest – Broad & Phrase",
            "targeting_type": "manual",
            "status": "enabled",
            "daily_budget": 75.00,
            "start_date": "2024-01-01",
            "end_date": None,
            "bidding_strategy": "LEGACY_FOR_SALES",
        },
        {
            "amazon_campaign_id": 1003,
            "ad_product": "SP",
            "name": "Auto Discovery",
            "targeting_type": "auto",
            "status": "enabled",
            "daily_budget": 50.00,
            "start_date": "2024-02-01",
            "end_date": None,
            "bidding_strategy": "AUTO_FOR_SALES",
        },
        {
            "amazon_campaign_id": 1004,
            "ad_product": "SB",
            "name": "Sponsored Brands – Header Ad",
            "targeting_type": "manual",
            "status": "enabled",
            "daily_budget": 150.00,
            "start_date": "2024-01-15",
            "end_date": None,
            "bidding_strategy": None,
        },
    ],
    9999000000002: [
        {
            "amazon_campaign_id": 1005,
            "ad_product": "SP",
            "name": "CA Brand Defense – Exact",
            "targeting_type": "manual",
            "status": "enabled",
            "daily_budget": 60.00,
            "start_date": "2024-03-01",
            "end_date": None,
            "bidding_strategy": "LEGACY_FOR_SALES",
        },
        {
            "amazon_campaign_id": 1006,
            "ad_product": "SP",
            "name": "CA Auto Discovery",
            "targeting_type": "auto",
            "status": "paused",
            "daily_budget": 30.00,
            "start_date": "2024-03-01",
            "end_date": None,
            "bidding_strategy": "AUTO_FOR_SALES",
        },
    ],
}

# Normalised ad groups keyed by amazon_profile_id
_MOCK_AD_GROUPS: dict[int, list[dict[str, Any]]] = {
    9999000000001: [
        {"amazon_ad_group_id": 2001, "amazon_campaign_id": 1001, "name": "Exact – Core Brand Terms",       "default_bid": 2.50, "status": "enabled"},
        {"amazon_ad_group_id": 2002, "amazon_campaign_id": 1001, "name": "Exact – Competitor Conquesting", "default_bid": 1.75, "status": "enabled"},
        {"amazon_ad_group_id": 2003, "amazon_campaign_id": 1002, "name": "Broad & Phrase Exploration",     "default_bid": 0.90, "status": "enabled"},
        {"amazon_ad_group_id": 2004, "amazon_campaign_id": 1003, "name": "Auto – All ASINs",               "default_bid": 1.20, "status": "enabled"},
        {"amazon_ad_group_id": 2005, "amazon_campaign_id": 1004, "name": "SB – Brand Keywords",            "default_bid": 2.00, "status": "enabled"},
    ],
    9999000000002: [
        {"amazon_ad_group_id": 2006, "amazon_campaign_id": 1005, "name": "CA Exact – Core Terms", "default_bid": 2.00, "status": "enabled"},
        {"amazon_ad_group_id": 2007, "amazon_campaign_id": 1006, "name": "CA Auto – Main ASINs",  "default_bid": 1.10, "status": "paused"},
    ],
}

# Normalised targets keyed by amazon_profile_id
_MOCK_TARGETS: dict[int, list[dict[str, Any]]] = {
    9999000000001: [
        {"amazon_target_id": 3001, "amazon_ad_group_id": 2001, "target_kind": "keyword", "match_type": "exact",  "expression_text": "ergonomic mouse pad",                                          "bid": 3.00, "status": "enabled"},
        {"amazon_target_id": 3002, "amazon_ad_group_id": 2001, "target_kind": "keyword", "match_type": "exact",  "expression_text": "premium desk mat",                                             "bid": 2.75, "status": "enabled"},
        {"amazon_target_id": 3003, "amazon_ad_group_id": 2001, "target_kind": "keyword", "match_type": "exact",  "expression_text": "large gaming mouse pad",                                       "bid": 2.50, "status": "enabled"},
        {"amazon_target_id": 3004, "amazon_ad_group_id": 2001, "target_kind": "keyword", "match_type": "exact",  "expression_text": "xl desk pad for computer",                                     "bid": 2.25, "status": "paused"},
        {"amazon_target_id": 3005, "amazon_ad_group_id": 2002, "target_kind": "keyword", "match_type": "exact",  "expression_text": "logitech g desk pad",                                          "bid": 1.80, "status": "enabled"},
        {"amazon_target_id": 3006, "amazon_ad_group_id": 2002, "target_kind": "keyword", "match_type": "exact",  "expression_text": "corsair mm300 extended",                                       "bid": 1.60, "status": "enabled"},
        {"amazon_target_id": 3007, "amazon_ad_group_id": 2002, "target_kind": "keyword", "match_type": "exact",  "expression_text": "steelseries qck heavy xl",                                     "bid": 1.55, "status": "paused"},
        {"amazon_target_id": 3008, "amazon_ad_group_id": 2003, "target_kind": "keyword", "match_type": "broad",  "expression_text": "mouse pad",                                                    "bid": 0.80, "status": "enabled"},
        {"amazon_target_id": 3009, "amazon_ad_group_id": 2003, "target_kind": "keyword", "match_type": "phrase", "expression_text": "desk mat",                                                     "bid": 0.95, "status": "enabled"},
        {"amazon_target_id": 3010, "amazon_ad_group_id": 2003, "target_kind": "keyword", "match_type": "broad",  "expression_text": "office desk accessories",                                      "bid": 0.70, "status": "enabled"},
        {"amazon_target_id": 3011, "amazon_ad_group_id": 2003, "target_kind": "product", "match_type": None,     "expression_text": '[{"type":"asinSameAs","value":"B08ABC12345"}]',                  "bid": 1.10, "status": "enabled"},
        {"amazon_target_id": 3012, "amazon_ad_group_id": 2003, "target_kind": "product", "match_type": None,     "expression_text": '[{"type":"asinSameAs","value":"B08DEF67890"}]',                  "bid": 1.05, "status": "enabled"},
        {"amazon_target_id": 3013, "amazon_ad_group_id": 2003, "target_kind": "product", "match_type": None,     "expression_text": '[{"type":"asinCategorySameAs","value":"2045326011"}]',            "bid": 0.85, "status": "paused"},
        {"amazon_target_id": 3014, "amazon_ad_group_id": 2005, "target_kind": "keyword", "match_type": "exact",  "expression_text": "ergonomic mouse pad",                                          "bid": 2.50, "status": "enabled"},
        {"amazon_target_id": 3015, "amazon_ad_group_id": 2005, "target_kind": "keyword", "match_type": "phrase", "expression_text": "best desk mat for gaming",                                     "bid": 1.90, "status": "enabled"},
        {"amazon_target_id": 3016, "amazon_ad_group_id": 2005, "target_kind": "keyword", "match_type": "broad",  "expression_text": "desk accessories",                                             "bid": 1.40, "status": "enabled"},
    ],
    9999000000002: [
        {"amazon_target_id": 3017, "amazon_ad_group_id": 2006, "target_kind": "keyword", "match_type": "exact",  "expression_text": "ergonomic mouse pad",                                          "bid": 2.00, "status": "enabled"},
        {"amazon_target_id": 3018, "amazon_ad_group_id": 2006, "target_kind": "keyword", "match_type": "phrase", "expression_text": "tapis de souris grand",                                        "bid": 1.50, "status": "enabled"},
        {"amazon_target_id": 3019, "amazon_ad_group_id": 2006, "target_kind": "product", "match_type": None,     "expression_text": '[{"type":"asinSameAs","value":"B08ABC12345"}]',                  "bid": 1.20, "status": "enabled"},
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ad_api_headers(
    access_token: str,
    profile_id: int,
    content_type: str = "application/json",
) -> dict[str, str]:
    """Build standard Amazon Ads API request headers.

    Pass a vendor-specific content_type for v3/v4 list endpoints, e.g.:
      'application/vnd.spCampaign.v3+json'
    """
    return {
        "Authorization": f"Bearer {access_token}",
        "Amazon-Advertising-API-ClientId": settings.amazon_client_id,
        "Amazon-Advertising-API-Scope": str(profile_id),
        "Content-Type": content_type,
        "Accept": content_type,
    }


def _parse_amazon_date(value: str | None) -> str | None:
    """Convert Amazon's YYYYMMDD date strings to ISO YYYY-MM-DD.
    v3/v4 already return ISO format — this function is idempotent."""
    if not value:
        return None
    value = str(value).strip()
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def _post_list_paginated(
    url: str,
    headers: dict[str, str],
    initial_body: dict[str, Any],
    data_key: str,
    max_pages: int = 0,
) -> tuple[list[dict[str, Any]], bool, int]:
    """POST to a v3/v4 list endpoint and follow nextToken pagination.

    Args:
        url:          Full endpoint URL.
        headers:      Request headers (include Content-Type for this endpoint).
        initial_body: Request body for the first page.
        data_key:     Key in the response JSON that holds the items list.
        max_pages:    Hard page cap (0 = unlimited). Use for keyword/target calls
                      on large accounts to bound sync time. Logs a warning when
                      the limit is hit so the truncation is visible in logs.

    Returns:
        Tuple of (items, was_truncated). was_truncated is True when max_pages
        was hit before exhausting Amazon's nextToken cursor, meaning the
        returned list is a partial view of Amazon's full inventory.
        Callers should skip soft_delete_missing when was_truncated is True.
    """
    results: list[dict[str, Any]] = []
    body = dict(initial_body)
    page_count = 0
    was_truncated = False
    while True:
        resp = _request_with_retry("POST", url, json=body, headers=headers, timeout=30)
        _raise_for_amazon_error(resp)
        data = resp.json()
        items = data.get(data_key) or []
        results.extend(items)
        page_count += 1
        next_token = data.get("nextToken")
        if not next_token or not items:
            break
        if max_pages > 0 and page_count >= max_pages:
            was_truncated = True
            logger.warning(
                "[amazon_ads] PAGE CAP REACHED: %s max_pages=%d fetched=%d (more exist on Amazon — soft_delete will be skipped)",
                url, max_pages, len(results),
            )
            break
        # Only carry nextToken forward; keep all other original body fields.
        body = {**initial_body, "nextToken": next_token}
    return results, was_truncated, page_count


def _get_list_paginated_sb(
    url: str,
    headers: dict[str, str],
    base_params: dict[str, Any],
    page_size: int = 1000,
    max_pages: int = 0,
) -> tuple[list[dict[str, Any]], bool, int]:
    """GET from a SB endpoint using startIndex/count offset pagination.

    Used for GET /sb/keywords and similar SB GET-style list endpoints
    that do NOT use cursor/nextToken pagination.

    Returns:
        Tuple of (items, was_truncated).
    """
    results: list[dict[str, Any]] = []
    start_index = 0
    page_count = 0
    was_truncated = False
    while True:
        params = {**base_params, "startIndex": start_index, "count": page_size}
        resp = _request_with_retry("GET", url, params=params, headers=headers, timeout=30)
        _raise_for_amazon_error(resp)
        data = resp.json()
        # SB GET endpoints may return a plain array or a wrapped object.
        if isinstance(data, list):
            items = data
        else:
            # Try common wrapper keys
            items = (
                data.get("keywords")
                or data.get("items")
                or []
            )
        results.extend(items)
        page_count += 1
        if len(items) < page_size:
            # Fewer than requested = last page
            break
        start_index += len(items)
        if max_pages > 0 and page_count >= max_pages:
            was_truncated = True
            logger.warning(
                "[amazon_ads] PAGE CAP REACHED (SB GET): %s max_pages=%d fetched=%d",
                url, max_pages, len(results),
            )
            break
    return results, was_truncated, page_count


# ---------------------------------------------------------------------------
# v3/v4 normaliser functions
# ---------------------------------------------------------------------------

def _normalize_sp_campaign_v3(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Sponsored Products v3 campaign object."""
    budget_obj = raw.get("budget") or {}
    bidding_obj = raw.get("dynamicBidding") or {}
    return {
        "amazon_campaign_id": int(raw["campaignId"]),
        "ad_product": "SP",
        "name": raw.get("name", ""),
        "targeting_type": _safe_targeting_type(raw.get("targetingType")),
        "status": _safe_status(raw.get("state")),
        "daily_budget": budget_obj.get("budget"),
        "start_date": _parse_amazon_date(raw.get("startDate")),
        "end_date": _parse_amazon_date(raw.get("endDate")),
        "bidding_strategy": bidding_obj.get("strategy"),
    }


def _normalize_sb_campaign_v4(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Sponsored Brands v4 campaign object."""
    # SB v4 budget may be a flat float or nested object depending on account type.
    budget = raw.get("budget")
    if isinstance(budget, dict):
        daily_budget = budget.get("budget")
    else:
        daily_budget = budget
    return {
        "amazon_campaign_id": int(raw["campaignId"]),
        "ad_product": "SB",
        "name": raw.get("name", ""),
        "targeting_type": "manual",  # SB campaigns are always manual targeting
        "status": _safe_status(raw.get("state")),
        "daily_budget": daily_budget,
        "start_date": _parse_amazon_date(raw.get("startDate")),
        "end_date": _parse_amazon_date(raw.get("endDate")),
        "bidding_strategy": None,
    }


def _normalize_ad_group_v3(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Sponsored Products v3 ad group object.
    In v3, defaultBid is a nested object: {bid: float}."""
    bid_obj = raw.get("defaultBid") or {}
    default_bid = bid_obj.get("bid") if isinstance(bid_obj, dict) else bid_obj
    return {
        "amazon_ad_group_id": int(raw["adGroupId"]),
        "amazon_campaign_id": int(raw["campaignId"]),
        "name": raw.get("name", ""),
        "default_bid": default_bid,
        "status": _safe_status(raw.get("state")),
    }


def _normalize_sb_ad_group_v4(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Sponsored Brands v4 ad group object."""
    return {
        "amazon_ad_group_id": int(raw["adGroupId"]),
        "amazon_campaign_id": int(raw["campaignId"]),
        "name": raw.get("name", ""),
        "default_bid": None,  # SB ad groups do not expose a default bid
        "status": _safe_status(raw.get("state")),
    }


def _normalize_keyword_v3(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Sponsored Products v3 keyword object.
    In v3, bid is a nested object: {bid: float}."""
    bid_obj = raw.get("bid") or {}
    bid = bid_obj.get("bid") if isinstance(bid_obj, dict) else bid_obj
    return {
        "amazon_target_id": int(raw["keywordId"]),
        "amazon_ad_group_id": int(raw["adGroupId"]),
        "target_kind": "keyword",
        "match_type": (raw.get("matchType") or "").lower() or None,
        "expression_text": raw.get("keywordText"),
        "bid": bid,
        "status": _safe_status(raw.get("state")),
    }


def _normalize_product_target_v3(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Sponsored Products v3 targeting clause (product target).
    In v3, bid is a nested object: {bid: float}. The response key is
    'targetingClauses' and each item's ID field is 'targetId'."""
    import json
    bid_obj = raw.get("bid") or {}
    bid = bid_obj.get("bid") if isinstance(bid_obj, dict) else bid_obj
    expr = raw.get("expression") or []
    return {
        "amazon_target_id": int(raw["targetId"]),
        "amazon_ad_group_id": int(raw["adGroupId"]),
        "target_kind": "product",
        "match_type": None,
        "expression_text": json.dumps(expr) if expr else None,
        "bid": bid,
        "status": _safe_status(raw.get("state")),
    }


def _normalize_sb_keyword_v3(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Sponsored Brands v3 keyword object."""
    bid_obj = raw.get("bid") or {}
    bid = bid_obj.get("bid") if isinstance(bid_obj, dict) else (bid_obj or raw.get("bidAmount"))
    return {
        "amazon_target_id": int(raw["keywordId"]),
        "amazon_ad_group_id": int(raw["adGroupId"]),
        "target_kind": "keyword",
        "match_type": (raw.get("matchType") or "").lower() or None,
        "expression_text": raw.get("keywordText"),
        "bid": bid,
        "status": _safe_status(raw.get("state")),
    }


# ---------------------------------------------------------------------------
# Public API — auth / profile
# ---------------------------------------------------------------------------

def build_auth_url(state: str) -> str:
    params = {
        "client_id": settings.amazon_client_id,
        "scope": "advertising::campaign_management",
        "response_type": "code",
        "redirect_uri": settings.amazon_redirect_uri,
        "state": state,
    }
    return f"{AMAZON_AUTH_BASE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(code: str) -> dict[str, Any]:
    """
    Exchange an authorization code for access + refresh tokens.
    Raises AmazonApiError with readable message on failure.
    """
    if settings.amazon_mock_mode:
        logger.info("[amazon_ads] MOCK: exchange_code_for_tokens")
        return {
            "access_token": f"mock_access_token_{code[:8]}",
            "refresh_token": f"mock_refresh_token_{code[:8]}",
            "expires_in": 3600,
        }
    resp = requests.post(
        AMAZON_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.amazon_redirect_uri,
            "client_id": settings.amazon_client_id,
            "client_secret": settings.amazon_client_secret,
        },
        timeout=15,
    )
    _raise_for_amazon_error(resp)
    return resp.json()


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """
    Refresh an access token using a stored refresh token.
    Raises AmazonApiError with readable message on failure.
    """
    if settings.amazon_mock_mode:
        logger.info("[amazon_ads] MOCK: refresh_access_token")
        return {"access_token": "mock_refreshed_access_token", "expires_in": 3600}
    resp = requests.post(
        AMAZON_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.amazon_client_id,
            "client_secret": settings.amazon_client_secret,
        },
        timeout=15,
    )
    _raise_for_amazon_error(resp)
    return resp.json()


def list_profiles(access_token: str) -> list[dict[str, Any]]:
    """
    Return all Amazon Ads profiles the token can access.
    /v2/profiles is the correct endpoint — profiles are not versioned like campaigns.
    Raises AmazonApiError with readable message on failure.
    """
    if settings.amazon_mock_mode:
        logger.info("[amazon_ads] MOCK: list_profiles — %d profiles", len(_MOCK_PROFILES))
        return _MOCK_PROFILES
    resp = requests.get(
        f"{settings.amazon_api_base_url}/v2/profiles",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Amazon-Advertising-API-ClientId": settings.amazon_client_id,
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    _raise_for_amazon_error(resp)
    return resp.json()


# ---------------------------------------------------------------------------
# Public API — campaign sync (v3/v4)
# ---------------------------------------------------------------------------

def list_campaigns(access_token: str, profile_id: int) -> list[dict[str, Any]]:
    """
    Return all campaigns (SP v3 + SB v4) for a profile in normalised form.

    SP v3: POST /sp/campaigns/list  (Content-Type: application/vnd.spCampaign.v3+json)
    SB v4: POST /sb/v4/campaigns/list  (Content-Type: application/vnd.sbCampaignResource.v4+json)

    Raises PartialFetchError if any sub-fetch failed. The exception carries
    whatever was successfully fetched, so callers can persist partial data
    while still knowing the view is incomplete.
    """
    if settings.amazon_mock_mode:
        data = _MOCK_CAMPAIGNS.get(profile_id, [])
        logger.info("[amazon_ads] MOCK: list_campaigns profile=%s — %d campaigns", profile_id, len(data))
        return data

    campaigns: list[dict[str, Any]] = []
    failures: list[str] = []

    # --- Sponsored Products v3 ---
    try:
        headers = _ad_api_headers(access_token, profile_id, "application/vnd.spCampaign.v3+json")
        body: dict[str, Any] = {
            "stateFilter": {"include": ["ENABLED", "PAUSED", "ARCHIVED"]},
            "maxResults": 1000,
        }
        raw, _, _ = _post_list_paginated(
            f"{settings.amazon_api_base_url}/sp/campaigns/list",
            headers, body, "campaigns",
        )
        campaigns.extend(_normalize_sp_campaign_v3(c) for c in raw)
        logger.info("[amazon_ads] SP campaigns v3 profile=%s: %d campaigns", profile_id, len(raw))
    except Exception as exc:
        msg = f"SP campaigns fetch failed for profile {profile_id}: {exc}"
        logger.error("[amazon_ads] %s", msg)
        failures.append(msg)

    # --- Sponsored Brands v4 ---
    try:
        headers = _ad_api_headers(access_token, profile_id, "application/vnd.sbCampaignResource.v4+json")
        body = {
            "stateFilter": {"include": ["ENABLED", "PAUSED", "ARCHIVED"]},
            "maxResults": 100,  # SB v4 hard cap; SP v3 allows 1000
        }
        raw, _, _ = _post_list_paginated(
            f"{settings.amazon_api_base_url}/sb/v4/campaigns/list",
            headers, body, "campaigns",
        )
        campaigns.extend(_normalize_sb_campaign_v4(c) for c in raw)
        logger.info("[amazon_ads] SB campaigns v4 profile=%s: %d campaigns", profile_id, len(raw))
    except Exception as exc:
        msg = f"SB campaigns fetch failed for profile {profile_id}: {exc}"
        logger.error("[amazon_ads] %s", msg)
        failures.append(msg)

    if failures:
        raise PartialFetchError(
            f"Campaign fetch incomplete for profile {profile_id}: " + "; ".join(failures),
            campaigns,
            failures,
        )
    return campaigns


def list_ad_groups(access_token: str, profile_id: int) -> list[dict[str, Any]]:
    """
    Return all ad groups (SP v3 + SB v4) for a profile in normalised form.

    SP v3: POST /sp/adGroups/list  (Content-Type: application/vnd.spAdGroup.v3+json)
    SB v4: POST /sb/v4/adGroups/list  (Content-Type: application/vnd.sbAdGroupResource.v4+json)
    """
    if settings.amazon_mock_mode:
        data = _MOCK_AD_GROUPS.get(profile_id, [])
        logger.info("[amazon_ads] MOCK: list_ad_groups profile=%s — %d ad groups", profile_id, len(data))
        return data

    ad_groups: list[dict[str, Any]] = []
    failures: list[str] = []

    # --- SP Ad Groups v3 ---
    try:
        headers = _ad_api_headers(access_token, profile_id, "application/vnd.spAdGroup.v3+json")
        body: dict[str, Any] = {
            "stateFilter": {"include": ["ENABLED", "PAUSED", "ARCHIVED"]},
            "maxResults": 1000,
        }
        raw, _, _ = _post_list_paginated(
            f"{settings.amazon_api_base_url}/sp/adGroups/list",
            headers, body, "adGroups",
        )
        ad_groups.extend(_normalize_ad_group_v3(g) for g in raw)
        logger.info("[amazon_ads] SP ad groups v3 profile=%s: %d ad groups", profile_id, len(raw))
    except Exception as exc:
        msg = f"SP ad groups fetch failed for profile {profile_id}: {exc}"
        logger.error("[amazon_ads] %s", msg)
        failures.append(msg)

    # --- SB Ad Groups v4 ---
    try:
        headers = _ad_api_headers(access_token, profile_id, "application/vnd.sbAdGroupResource.v4+json")
        body = {
            "stateFilter": {"include": ["ENABLED", "PAUSED", "ARCHIVED"]},
            "maxResults": 100,  # SB v4 hard cap; SP v3 allows 1000
        }
        raw, _, _ = _post_list_paginated(
            f"{settings.amazon_api_base_url}/sb/v4/adGroups/list",
            headers, body, "adGroups",
        )
        ad_groups.extend(_normalize_sb_ad_group_v4(g) for g in raw)
        logger.info("[amazon_ads] SB ad groups v4 profile=%s: %d ad groups", profile_id, len(raw))
    except Exception as exc:
        msg = f"SB ad groups fetch failed for profile {profile_id}: {exc}"
        logger.error("[amazon_ads] %s", msg)
        failures.append(msg)

    if failures:
        raise PartialFetchError(
            f"Ad group fetch incomplete for profile {profile_id}: " + "; ".join(failures),
            ad_groups,
            failures,
        )
    return ad_groups


def list_targets(access_token: str, profile_id: int) -> tuple[list[dict[str, Any]], bool, int, int]:
    """
    Return all keyword and product targets for a profile in normalised form.

    SP Keywords v3:        POST /sp/keywords/list  (max_pages=50 → 50k cap)
    SP Product Targets v3: POST /sp/targets/list   (max_pages=20 → 20k cap)
    SB Keywords v3.2:      GET /sb/keywords        (offset pagination, Accept: vnd.sbkeyword.v3.2+json)

    Returns:
        (targets, was_truncated) — was_truncated is True when any SP call hit
        its page cap and returned a partial view. Callers (sync_targets) must
        skip soft_delete_missing when was_truncated is True to avoid incorrectly
        marking Amazon keywords as deleted just because we didn't fetch them.
    """
    if settings.amazon_mock_mode:
        data = _MOCK_TARGETS.get(profile_id, [])
        logger.info("[amazon_ads] MOCK: list_targets profile=%s — %d targets", profile_id, len(data))
        return data, False, 0, len(data)

    targets: list[dict[str, Any]] = []
    failures: list[str] = []
    was_truncated = False

    # Safety cap: 0 = unlimited full sync (default). Set AMAZON_FULL_SYNC_MAX_PAGES>0 for emergency guard.
    max_pages_cap = settings.amazon_full_sync_max_pages
    total_pages = 0

    # --- SP Keywords v3 ---
    try:
        headers = _ad_api_headers(access_token, profile_id, "application/vnd.spKeyword.v3+json")
        body: dict[str, Any] = {
            "stateFilter": {"include": ["ENABLED", "PAUSED", "ARCHIVED"]},
            "maxResults": 1000,
        }
        raw, kw_truncated, kw_pages = _post_list_paginated(
            f"{settings.amazon_api_base_url}/sp/keywords/list",
            headers, body, "keywords",
            max_pages=max_pages_cap,
        )
        total_pages += kw_pages
        if kw_truncated:
            was_truncated = True
            logger.warning("[amazon_ads] SP keywords TRUNCATED profile=%s pages=%d rows=%d cap=%d", profile_id, kw_pages, len(raw), max_pages_cap)
        targets.extend(_normalize_keyword_v3(k) for k in raw)
        logger.info("[amazon_ads] SP keywords v3 profile=%s: %d keywords pages=%d", profile_id, len(raw), kw_pages)
    except Exception as exc:
        msg = f"SP keywords fetch failed for profile {profile_id}: {exc}"
        logger.error("[amazon_ads] %s", msg)
        failures.append(msg)

    # --- SP Product Targets v3 ---
    # Response key is "targetingClauses", not "targets"
      
    try:
        headers = _ad_api_headers(access_token, profile_id, "application/vnd.spTargetingClause.v3+json")
        body: dict[str, Any] = {
            "stateFilter": {"include": ["ENABLED", "PAUSED", "ARCHIVED"]},
            "maxResults": 1000,
        }
        raw, pt_truncated, pt_pages = _post_list_paginated(
            f"{settings.amazon_api_base_url}/sp/targets/list",
            headers, body, "targetingClauses",
            max_pages=max_pages_cap,
        )
        total_pages += pt_pages
        if pt_truncated:
            was_truncated = True
            logger.warning("[amazon_ads] SP targets TRUNCATED profile=%s pages=%d rows=%d cap=%d", profile_id, pt_pages, len(raw), max_pages_cap)
        targets.extend(_normalize_product_target_v3(t) for t in raw)
        logger.info("[amazon_ads] SP product targets v3 profile=%s: %d targets pages=%d", profile_id, len(raw), pt_pages)
    except Exception as exc:
        msg = f"SP product targets fetch failed for profile {profile_id}: {exc}"
        logger.error("[amazon_ads] %s", msg)
        failures.append(msg)

    # --- SB Keywords (GET /sb/keywords, offset-based pagination) ---
    # NOTE: /sb/v4/keywords/list does not exist — Amazon returns a misleading 403.
    # The correct endpoint is the v3-style GET with Accept: vnd.sbkeyword.v3.2+json.
    try:
        sb_kw_headers = {
            "Authorization": f"Bearer {access_token}",
            "Amazon-Advertising-API-ClientId": settings.amazon_client_id,
            "Amazon-Advertising-API-Scope": str(profile_id),
            "Accept": "application/vnd.sbkeyword.v3.2+json",
        }
        sb_kw_params = {
            "stateFilter": "enabled,paused,archived",
        }
        raw, _, sb_pages = _get_list_paginated_sb(
            f"{settings.amazon_api_base_url}/sb/keywords",
            sb_kw_headers,
            sb_kw_params,
            page_size=1000,
            max_pages=max_pages_cap,
        )
        total_pages += sb_pages
        targets.extend(_normalize_sb_keyword_v3(k) for k in raw)
        logger.info("[amazon_ads] SB keywords GET profile=%s: %d keywords pages=%d", profile_id, len(raw), sb_pages)
    except Exception as exc:
        msg = f"SB keywords fetch failed for profile {profile_id}: {exc}"
        logger.error("[amazon_ads] %s", msg)
        failures.append(msg)

    total_rows = len(targets)
    logger.info(
        "[amazon_ads] list_targets COMPLETE profile=%s pages=%d rows=%d truncated=%s cap=%d failures=%d",
        profile_id, total_pages, total_rows, was_truncated, max_pages_cap, len(failures),
    )
    if failures:
        raise PartialFetchError(
            f"Target fetch incomplete for profile {profile_id}: " + "; ".join(failures),
            targets,
            failures,
        )
    return targets, was_truncated, total_pages, total_rows
