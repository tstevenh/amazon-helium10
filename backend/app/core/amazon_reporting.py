"""
Amazon Advertising Reporting API v3 client.

Implements the async 3-step report flow:
  1. POST /reporting/reports        — request a report, get reportId
  2. GET  /reporting/reports/{id}   — poll until status == "COMPLETED"
  3. GET  report.url                — download gzip JSON, parse rows

Supported report types (Sponsored Products, DAILY granularity):
  - spCampaigns   → campaign-level metrics
  - spCampaigns + groupBy:adGroup → ad group-level metrics
  - spTargeting   → target-level metrics (keywords + product targets)

All functions accept an access_token + profile_id and return a list of
normalised dicts with snake_case keys. No raw Amazon field names escape
this module.

Mock mode
---------
When AMAZON_MOCK_MODE=true, every function returns realistic dummy rows
instead of hitting Amazon's servers.

Error handling
--------------
Raises AmazonApiError (from amazon_ads module) on non-2xx responses.
Raises RuntimeError if poll times out.
"""
import gzip
import json
import logging
import time
from datetime import date, timedelta
from typing import Any, Callable, Optional

import requests

from app.config import settings
from app.core.amazon_ads import AmazonApiError, _raise_for_amazon_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPORTING_BASE = settings.amazon_api_base_url  # same base as Ads API

# Campaign-level metrics — only columns confirmed valid by Amazon SP Reporting v3
_CAMPAIGN_METRICS = [
    "date",  # must be requested explicitly — v3 does not auto-include it
    "campaignId", "campaignName",
    "impressions", "clicks", "cost", "purchases7d", "sales7d",
    "clickThroughRate", "costPerClick",
]

# Ad group-level metrics — requested via spCampaigns + groupBy:adGroup
# because spAdGroups reportTypeId is not available for all account types
_AD_GROUP_METRICS = [
    "date",  # must be requested explicitly — v3 does not auto-include it
    # NOTE: campaignId is NOT valid for spCampaigns+groupBy:adGroup
    "adGroupId", "adGroupName",
    "impressions", "clicks", "cost", "purchases7d", "sales7d",
    "clickThroughRate", "costPerClick",
]

# Target-level metrics — targetId/keywordText/targetingExpressionType
# are not valid v3 columns; use keyword + matchType + adGroupId to identify rows
_TARGETING_METRICS = [
    "date",  # must be requested explicitly — v3 does not auto-include it
    "campaignId", "adGroupId", "matchType", "keyword",
    "impressions", "clicks", "cost", "purchases7d", "sales7d",
    "clickThroughRate", "costPerClick",
]

# Poll settings
_POLL_MAX_ATTEMPTS = 180    # 180 × 10s = 30 minutes max
_POLL_INTERVAL_SEC = 10
_REPORT_MAX_DAYS   = 31     # Amazon SP Reporting API v3: max 31 days per request


# ---------------------------------------------------------------------------
# Header helper
# ---------------------------------------------------------------------------

def _report_headers(access_token: str, profile_id: int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Amazon-Advertising-API-ClientId": settings.amazon_client_id,
        "Amazon-Advertising-API-Scope": str(profile_id),
        "Content-Type": "application/vnd.createasyncreportrequest.v3+json",
        "Accept": "application/vnd.createasyncreportrequest.v3+json",
    }


# ---------------------------------------------------------------------------
# Core async report flow
# ---------------------------------------------------------------------------

def _request_report(
    access_token: str,
    profile_id: int,
    report_type: str,
    columns: list[str],
    start_date: date,
    end_date: date,
    group_by: list[str] | None = None,
) -> str:
    """POST /reporting/reports and return reportId."""
    if group_by is None:
        group_by = (["campaign"] if report_type == "spCampaigns" else
                    ["adGroup"] if report_type == "spAdGroups" else ["targeting"])
    url = f"{_REPORTING_BASE}/reporting/reports"
    body = {
        "name": f"ppc-os-{report_type}-{start_date}-{end_date}",
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "configuration": {
            "adProduct": "SPONSORED_PRODUCTS",
            "groupBy": group_by,
            "columns": columns,
            "reportTypeId": report_type,
            "timeUnit": "DAILY",
            "format": "GZIP_JSON",
        },
    }
    resp = requests.post(url, json=body, headers=_report_headers(access_token, profile_id), timeout=30)
    _raise_for_amazon_error(resp)
    data = resp.json()
    report_id = data.get("reportId", "")
    if not report_id:
        raise AmazonApiError(f"No reportId in response: {data}")
    logger.warning("[reporting] Requested %s report %s for profile %s (%s -> %s) groupBy=%s",
                   report_type, report_id, profile_id, start_date, end_date, group_by)
    return report_id


def _poll_report(access_token: str, profile_id: int, report_id: str) -> dict[str, Any]:
    """Poll GET /reporting/reports/{id} until COMPLETED or failure."""
    url = f"{_REPORTING_BASE}/reporting/reports/{report_id}"
    poll_headers = {
        "Authorization": f"Bearer {access_token}",
        "Amazon-Advertising-API-ClientId": settings.amazon_client_id,
        "Amazon-Advertising-API-Scope": str(profile_id),
        "Accept": "application/vnd.createasyncreportrequest.v3+json",
    }
    for attempt in range(1, _POLL_MAX_ATTEMPTS + 1):
        resp = requests.get(url, headers=poll_headers, timeout=30)
        _raise_for_amazon_error(resp)
        data = resp.json()
        status = data.get("status", "")
        logger.warning("[reporting] Poll attempt %d report %s status=%s", attempt, report_id, status)
        if status == "COMPLETED":
            return data
        if status in ("FAILURE", "CANCELLED"):
            raise AmazonApiError(f"Report {report_id} ended with status {status}: {data.get('statusDetails', '')}")
        time.sleep(_POLL_INTERVAL_SEC)
    raise RuntimeError(f"Report {report_id} did not complete after {_POLL_MAX_ATTEMPTS} polls")


def _download_report(report_url: str) -> list[dict[str, Any]]:
    """Download gzip JSON from presigned S3 URL, return parsed rows."""
    resp = requests.get(report_url, timeout=120)
    if not resp.ok:
        raise AmazonApiError(f"Report download failed: HTTP {resp.status_code}")
    try:
        raw_bytes = gzip.decompress(resp.content)
        rows: list[dict[str, Any]] = json.loads(raw_bytes)
        logger.warning("[reporting] Downloaded %d rows", len(rows))
        return rows
    except Exception as exc:
        raise AmazonApiError(f"Failed to decompress/parse report: {exc}") from exc


def _fetch_report(
    access_token: str,
    profile_id: int,
    report_type: str,
    columns: list[str],
    start_date: date,
    end_date: date,
    group_by: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Full 3-step flow: request -> poll -> download."""
    report_id = _request_report(access_token, profile_id, report_type, columns,
                                start_date, end_date, group_by)
    report_meta = _poll_report(access_token, profile_id, report_id)
    report_url = report_meta.get("url", "")
    if not report_url:
        raise AmazonApiError(f"No download URL in completed report: {report_meta}")
    return _download_report(report_url)


def _fetch_report_chunked(
    access_token: str,
    profile_id: int,
    report_type: str,
    columns: list[str],
    start_date: date,
    end_date: date,
    group_by: list[str] | None = None,
    token_getter: Optional[Callable[[], str]] = None,
) -> list[dict[str, Any]]:
    """
    Fetch a report in <=31-day chunks and concatenate all rows.

    Amazon SP Reporting API v3 limits each request to a 31-day window.
    This function splits longer date ranges automatically.

    token_getter: if provided, called before each chunk to obtain a fresh
    access token. Long syncs (3 chunks x ~20 min each = 60 min) would
    otherwise expire the original 1-hour token before the final chunk.
    """
    all_rows: list[dict[str, Any]] = []
    chunk_start = start_date
    while chunk_start <= end_date:
        # Refresh token before every chunk — each chunk can take up to 30 min
        # to poll, so three chunks easily exceed the 60-min token lifetime.
        if token_getter is not None:
            access_token = token_getter()
            logger.warning("[reporting] Token refreshed before chunk %s (profile %s)",
                           chunk_start, profile_id)
        chunk_end = min(chunk_start + timedelta(days=_REPORT_MAX_DAYS - 1), end_date)
        rows = _fetch_report(access_token, profile_id, report_type, columns,
                             chunk_start, chunk_end, group_by)
        all_rows.extend(rows)
        logger.warning("[reporting] chunk %s->%s: %d rows (total so far: %d)",
                       chunk_start, chunk_end, len(rows), len(all_rows))
        chunk_start = chunk_end + timedelta(days=1)
    return all_rows


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _safe_decimal(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int:
    if v is None:
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Mock data helpers
# ---------------------------------------------------------------------------

def _mock_campaign_rows(start_date: date, end_date: date) -> list[dict[str, Any]]:
    rows = []
    d = start_date
    while d <= end_date:
        for cid in [1001, 1002, 1003]:
            rows.append({
                "date": d.isoformat(),
                "campaignId": str(cid),
                "impressions": 5000 + cid * 100,
                "clicks": 120 + cid * 5,
                "cost": round(150.0 + cid * 10, 2),
                "purchases7d": 8 + cid,
                "sales7d": round(400.0 + cid * 50, 2),
            })
        d += timedelta(days=1)
    return rows


def _mock_ad_group_rows(start_date: date, end_date: date) -> list[dict[str, Any]]:
    rows = []
    d = start_date
    while d <= end_date:
        for cid, agid in [(1001, 2001), (1001, 2002), (1002, 2003)]:
            rows.append({
                "date": d.isoformat(),
                "campaignId": str(cid),
                "adGroupId": str(agid),
                "impressions": 2500,
                "clicks": 60,
                "cost": round(75.0 + agid * 0.01, 2),
                "purchases7d": 4,
                "sales7d": round(200.0 + agid * 0.1, 2),
            })
        d += timedelta(days=1)
    return rows


def _mock_targeting_rows(start_date: date, end_date: date) -> list[dict[str, Any]]:
    rows = []
    d = start_date
    while d <= end_date:
        for agid, kw, mt in [(2001, "ice cube tray", "exact"), (2001, "silicone tray", "phrase"), (2002, "freezer tray", "broad")]:
            rows.append({
                "date": d.isoformat(),
                "campaignId": "1001",
                "adGroupId": str(agid),
                "matchType": mt,
                "keyword": kw,
                "impressions": 800,
                "clicks": 20,
                "cost": round(25.0, 2),
                "purchases7d": 1,
                "sales7d": round(60.0, 2),
            })
        d += timedelta(days=1)
    return rows


# ---------------------------------------------------------------------------
# Public API — campaign performance
# ---------------------------------------------------------------------------

def fetch_campaign_performance(
    access_token: str,
    profile_id: int,
    start_date: date,
    end_date: date,
    token_getter: Optional[Callable[[], str]] = None,
) -> list[dict[str, Any]]:
    """
    Fetch SP campaign-level daily performance.

    Returns list of normalised dicts:
      amazon_campaign_id, date, impressions, clicks, spend, sales, orders,
      ctr, cpc, acos, roas

    token_getter: optional callable that returns a fresh access token.
    When provided, the token is refreshed before each 31-day chunk so that
    long syncs spanning multiple chunks do not hit the 1-hour token expiry.
    """
    if settings.amazon_mock_mode:
        raw_rows = _mock_campaign_rows(start_date, end_date)
    else:
        raw_rows = _fetch_report_chunked(
            access_token, profile_id,
            "spCampaigns", _CAMPAIGN_METRICS,
            start_date, end_date,
            token_getter=token_getter,
        )

    normalised = []
    for r in raw_rows:
        spend = _safe_decimal(r.get("cost")) or 0.0
        sales = _safe_decimal(r.get("sales7d")) or 0.0
        clicks = _safe_int(r.get("clicks"))
        impr = _safe_int(r.get("impressions"))
        orders = _safe_int(r.get("purchases7d"))
        normalised.append({
            "amazon_campaign_id": int(r["campaignId"]),
            "date": r.get("date"),
            "impressions": impr,
            "clicks": clicks,
            "spend": spend,
            "sales": sales,
            "orders": orders,
            "ctr": round(clicks / impr, 6) if impr else None,
            "cpc": round(spend / clicks, 4) if clicks else None,
            "acos": round(spend / sales * 100, 4) if sales else None,
            "roas": round(sales / spend, 4) if spend else None,
        })
    logger.warning("[reporting] fetch_campaign_performance profile=%s rows=%d", profile_id, len(normalised))
    return normalised


# ---------------------------------------------------------------------------
# Public API — ad group performance
# ---------------------------------------------------------------------------

def fetch_ad_group_performance(
    access_token: str,
    profile_id: int,
    start_date: date,
    end_date: date,
    token_getter: Optional[Callable[[], str]] = None,
) -> list[dict[str, Any]]:
    """
    Fetch SP ad-group-level daily performance.

    Uses spCampaigns reportTypeId with groupBy:adGroup since spAdGroups
    is not available for all account types.

    Returns list of normalised dicts:
      amazon_ad_group_id, amazon_campaign_id, date, impressions, clicks,
      spend, sales, orders, ctr, cpc, acos, roas

    token_getter: optional callable that returns a fresh access token.
    """
    if settings.amazon_mock_mode:
        raw_rows = _mock_ad_group_rows(start_date, end_date)
    else:
        raw_rows = _fetch_report_chunked(
            access_token, profile_id,
            "spCampaigns", _AD_GROUP_METRICS,
            start_date, end_date,
            group_by=["adGroup"],
            token_getter=token_getter,
        )

    normalised = []
    for r in raw_rows:
        ag_id_raw = r.get("adGroupId")
        if not ag_id_raw:
            continue
        spend = _safe_decimal(r.get("cost")) or 0.0
        sales = _safe_decimal(r.get("sales7d")) or 0.0
        clicks = _safe_int(r.get("clicks"))
        impr = _safe_int(r.get("impressions"))
        orders = _safe_int(r.get("purchases7d"))
        normalised.append({
            "amazon_ad_group_id": int(ag_id_raw),
            "date": r.get("date"),
            "impressions": impr,
            "clicks": clicks,
            "spend": spend,
            "sales": sales,
            "orders": orders,
            "ctr": round(clicks / impr, 6) if impr else None,
            "cpc": round(spend / clicks, 4) if clicks else None,
            "acos": round(spend / sales * 100, 4) if sales else None,
            "roas": round(sales / spend, 4) if spend else None,
        })
    logger.warning("[reporting] fetch_ad_group_performance profile=%s rows=%d", profile_id, len(normalised))
    return normalised


# ---------------------------------------------------------------------------
# Public API — target (keyword + product) performance
# ---------------------------------------------------------------------------

def fetch_target_performance(
    access_token: str,
    profile_id: int,
    start_date: date,
    end_date: date,
    token_getter: Optional[Callable[[], str]] = None,
) -> list[dict[str, Any]]:
    """
    Fetch SP targeting (keywords + product targets) daily performance.

    NOTE: Amazon SP Reporting v3 does not expose a targetId column.
    Rows are identified by (amazon_ad_group_id, match_type, keyword_text).
    Product targets (ASIN) will not match by this key and are skipped.

    Returns list of normalised dicts:
      amazon_ad_group_id, match_type, keyword_text, date,
      impressions, clicks, spend, sales, orders, ctr, cpc, acos, roas

    token_getter: optional callable that returns a fresh access token.
    """
    if settings.amazon_mock_mode:
        raw_rows = _mock_targeting_rows(start_date, end_date)
    else:
        raw_rows = _fetch_report_chunked(
            access_token, profile_id,
            "spTargeting", _TARGETING_METRICS,
            start_date, end_date,
            token_getter=token_getter,
        )

    normalised = []
    for r in raw_rows:
        ag_id_raw = r.get("adGroupId")
        if not ag_id_raw:
            continue
        spend = _safe_decimal(r.get("cost")) or 0.0
        sales = _safe_decimal(r.get("sales7d")) or 0.0
        clicks = _safe_int(r.get("clicks"))
        impr = _safe_int(r.get("impressions"))
        orders = _safe_int(r.get("purchases7d"))
        normalised.append({
            "amazon_ad_group_id": int(ag_id_raw),
            "match_type": (r.get("matchType") or "").lower(),
            "keyword_text": (r.get("keyword") or "").lower(),
            "date": r.get("date"),
            "impressions": impr,
            "clicks": clicks,
            "spend": spend,
            "sales": sales,
            "orders": orders,
            "ctr": round(clicks / impr, 6) if impr else None,
            "cpc": round(spend / clicks, 4) if clicks else None,
            "acos": round(spend / sales * 100, 4) if sales else None,
            "roas": round(sales / spend, 4) if spend else None,
        })
    logger.warning("[reporting] fetch_target_performance profile=%s rows=%d", profile_id, len(normalised))
    return normalised
