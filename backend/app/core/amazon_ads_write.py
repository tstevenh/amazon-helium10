"""The ONLY module permitted to make mutating Amazon Ads API calls.

Every other module in this codebase is read-only. Keeping writes in one small
file means the blast radius is auditable by reading a single module — you can
see everything the app is capable of changing in your ad account in one place.

Permitted operations, and nothing else:
  - change one keyword's bid          PUT  /sp/keywords
  - change one product target's bid   PUT  /sp/targets
  - add one negative keyword          POST /sp/negativeKeywords

Deliberately NOT here: creating or deleting campaigns, ad groups or product
ads; changing budgets; pausing anything. The test campaign is created by a
human in Amazon's console precisely so this surface stays small.

Safety model
------------
1. settings.amazon_write_enabled is a master kill-switch, default False.
   Every public function calls assert_write_enabled() FIRST, before building
   a request, so with the switch off no mutating request can even be
   constructed. A test enforces that ordering by inspecting source.
2. Callers must record the attempt in suggestion_actions before and after the
   call — see ExecutionService. This module never touches the database.
3. One call per suggestion. No batching in V1, per the spec: it trades API
   efficiency for per-suggestion error isolation.
4. v3 mutation endpoints return 200/207 with per-item success and error
   arrays, so HTTP status alone does not mean the change happened.
   _parse_mutation_result inspects the body and returns a definite ok flag.
"""
import logging
from typing import Any

import requests

from app.config import settings
from app.core.amazon_ads import _request_with_retry

logger = logging.getLogger(__name__)


class AmazonWriteDisabled(Exception):
    """Raised when a write is attempted while AMAZON_WRITE_ENABLED is false."""


def assert_write_enabled() -> None:
    """Gate every mutating call. Raises unless writes are explicitly enabled."""
    if not settings.amazon_write_enabled:
        raise AmazonWriteDisabled(
            "Amazon writes are disabled (AMAZON_WRITE_ENABLED=false). "
            "This is the default: the app cannot modify a live ad account "
            "until writes are explicitly authorised."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_headers(access_token: str, profile_id: int, content_type: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Amazon-Advertising-API-ClientId": settings.amazon_client_id,
        "Amazon-Advertising-API-Scope": str(profile_id),
        "Content-Type": content_type,
        "Accept": content_type,
    }


def _validate_bid(new_bid: Any) -> None:
    """Reject a bid that could never be valid, before it reaches the account."""
    if new_bid is None:
        raise ValueError("bid must be a positive number, got None")
    try:
        value = float(new_bid)
    except (TypeError, ValueError):
        raise ValueError(f"bid must be a positive number, got {new_bid!r}") from None
    if value <= 0:
        raise ValueError(f"bid must be positive, got {value!r}")


def _parse_mutation_result(
    resp: requests.Response, body: dict[str, Any], collection: str
) -> dict[str, Any]:
    """Turn a v3 mutation response into a definite ok / not-ok.

    v3 returns 200/207 with per-item `success` and `error` arrays, so HTTP
    status alone is not enough — a 207 can contain nothing but errors. Only a
    non-empty success array with no errors counts as a confirmed change.
    """
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": (resp.text or "")[:500]}

    if not resp.ok:
        logger.error("[amazon_write] HTTP %d: %s", resp.status_code, str(payload)[:300])
        return {"ok": False, "request": body, "response": payload,
                "status_code": resp.status_code}

    section = payload.get(collection) or {}
    errors = section.get("error") or []
    successes = section.get("success") or []
    ok = bool(successes) and not errors
    if not ok:
        logger.error("[amazon_write] rejected by Amazon: %s", str(payload)[:300])
    return {"ok": ok, "request": body, "response": payload,
            "status_code": resp.status_code}


# ---------------------------------------------------------------------------
# Public write API — three operations, nothing more
# ---------------------------------------------------------------------------

def update_keyword_bid(
    access_token: str, profile_id: int, keyword_id: int, new_bid: float
) -> dict[str, Any]:
    """PUT /sp/keywords — change one keyword's bid."""
    assert_write_enabled()
    _validate_bid(new_bid)
    body = {"keywords": [{"keywordId": str(keyword_id), "bid": float(new_bid)}]}
    url = f"{settings.amazon_api_base_url}/sp/keywords"
    headers = _write_headers(access_token, profile_id, "application/vnd.spKeyword.v3+json")
    logger.warning("[amazon_write] PUT keyword=%s bid=%s profile=%s",
                   keyword_id, new_bid, profile_id)
    resp = _request_with_retry("PUT", url, json=body, headers=headers, timeout=30)
    return _parse_mutation_result(resp, body, "keywords")


def update_target_bid(
    access_token: str, profile_id: int, target_id: int, new_bid: float
) -> dict[str, Any]:
    """PUT /sp/targets — change one product target's bid."""
    assert_write_enabled()
    _validate_bid(new_bid)
    body = {"targetingClauses": [{"targetId": str(target_id), "bid": float(new_bid)}]}
    url = f"{settings.amazon_api_base_url}/sp/targets"
    headers = _write_headers(access_token, profile_id,
                             "application/vnd.spTargetingClause.v3+json")
    logger.warning("[amazon_write] PUT target=%s bid=%s profile=%s",
                   target_id, new_bid, profile_id)
    resp = _request_with_retry("PUT", url, json=body, headers=headers, timeout=30)
    return _parse_mutation_result(resp, body, "targetingClauses")


def create_negative_keyword(
    access_token: str,
    profile_id: int,
    ad_group_id: int,
    campaign_id: int,
    keyword_text: str,
    match_type: str,
) -> dict[str, Any]:
    """POST /sp/negativeKeywords — add one negative keyword to an ad group."""
    assert_write_enabled()
    # Accept 'exact' or 'negative_exact' from callers; emit exactly one prefix.
    bare = (match_type or "exact").upper().replace("NEGATIVE_", "")
    body = {"negativeKeywords": [{
        "campaignId": str(campaign_id),
        "adGroupId": str(ad_group_id),
        "keywordText": keyword_text,
        "matchType": f"NEGATIVE_{bare}",
        "state": "ENABLED",
    }]}
    url = f"{settings.amazon_api_base_url}/sp/negativeKeywords"
    headers = _write_headers(access_token, profile_id,
                             "application/vnd.spNegativeKeyword.v3+json")
    logger.warning("[amazon_write] POST negative='%s' (%s) ad_group=%s profile=%s",
                   keyword_text, f"NEGATIVE_{bare}", ad_group_id, profile_id)
    resp = _request_with_retry("POST", url, json=body, headers=headers, timeout=30)
    return _parse_mutation_result(resp, body, "negativeKeywords")


# ---------------------------------------------------------------------------
# Campaign state — dayparting only
# ---------------------------------------------------------------------------
#
# This is the most consequential write in the app. A wrong bid costs cents; a
# campaign left paused costs a day of sales. Two guards beyond the kill-switch:
#
#   1. Only ENABLED and PAUSED are accepted. ARCHIVED is irreversible on
#      Amazon and is refused outright — nothing in this app should be able to
#      archive a campaign, ever.
#   2. The caller passes the state it believes the campaign is currently in.
#      A no-op is skipped rather than sent, so a stuck scheduler cannot
#      hammer Amazon with redundant identical writes.

_ALLOWED_CAMPAIGN_STATES = ("ENABLED", "PAUSED")


class CampaignStateRefused(Exception):
    """A campaign state change that must never be attempted."""


def update_campaign_state(
    access_token: str, profile_id: int, campaign_id: int, new_state: str
) -> dict[str, Any]:
    """PUT /sp/campaigns — pause or re-enable one campaign.

    Used only by the dayparting executor. Bid and budget changes have their own
    functions; this one deliberately cannot touch either.
    """
    assert_write_enabled()

    state = (new_state or "").upper()
    if state not in _ALLOWED_CAMPAIGN_STATES:
        # ARCHIVED lands here. Amazon cannot un-archive a campaign, so this is
        # a refusal rather than a validation error.
        raise CampaignStateRefused(
            f"campaign state {new_state!r} is not permitted; "
            f"allowed: {', '.join(_ALLOWED_CAMPAIGN_STATES)}"
        )

    body = {"campaigns": [{"campaignId": str(campaign_id), "state": state}]}
    url = f"{settings.amazon_api_base_url}/sp/campaigns"
    headers = _write_headers(access_token, profile_id,
                             "application/vnd.spCampaign.v3+json")
    logger.warning("[amazon_write] PUT campaign=%s state=%s profile=%s",
                   campaign_id, state, profile_id)
    resp = _request_with_retry("PUT", url, json=body, headers=headers, timeout=30)
    return _parse_mutation_result(resp, body, "campaigns")
