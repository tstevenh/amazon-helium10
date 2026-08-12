"""ONE-OFF: create a paused test campaign for verifying Amazon write access.

NOT part of the application. Deliberately a standalone script so the app's
write client stays limited to three endpoints (keyword bid, target bid,
negative keyword) and can never create campaigns. See
docs/superpowers/plans/2026-08-06-suggestion-execution-write-path.md.

Team constraint (2026-08-06):
    "If you want to test the API, never test on existing campaign,
     create 1 new campaign for test. Don't use existing."

What it creates
---------------
  1. Campaign  ZZ-API-TEST-DO-NOT-USE  — Sponsored Products, MANUAL,
                                          PAUSED, $1.00/day budget
  2. Ad group  ZZ-API-TEST-ADGROUP     — default bid $0.75
  3. Keyword   "zzapitestdonotuse"     — EXACT match, bid $0.75

No product ad is created. An ad group with no products cannot serve, so this
campaign is inert twice over: paused, and with nothing to advertise. The
keyword text is nonsense so it could never match a real shopper query even if
someone unpaused it by accident.

$0.75 is deliberately distinctive — when we later verify a bid change, the
value cannot be confused with anything else in the account.

Usage
-----
    # Show exactly what would be sent, change nothing (default):
    docker compose exec -T api python /app/scripts/create_test_campaign.py

    # Actually create it (requires AMAZON_WRITE_ENABLED=true):
    docker compose exec -T api python /app/scripts/create_test_campaign.py --confirm

Cleanup: archive the campaign in the Amazon console when finished. Amazon
does not permit hard deletion of campaigns.
"""
import argparse
import json
import sys
from datetime import date

import requests

from app.config import settings
from app.core.amazon_ads_write import assert_write_enabled
from app.database import SessionLocal
from app.modules.accounts.models import AdsProfile, SellerAccount
from app.modules.accounts.service import AccountService

CAMPAIGN_NAME = "ZZ-API-TEST-DO-NOT-USE"
AD_GROUP_NAME = "ZZ-API-TEST-ADGROUP"
KEYWORD_TEXT = "zzapitestdonotuse"
BID = 0.75
DAILY_BUDGET = 1.00


def _headers(token: str, profile_id: int, content_type: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Amazon-Advertising-API-ClientId": settings.amazon_client_id,
        "Amazon-Advertising-API-Scope": str(profile_id),
        "Content-Type": content_type,
        "Accept": content_type,
    }


def _post(url: str, body: dict, headers: dict, label: str, dry_run: bool):
    print(f"\n--- {label} ---")
    print(f"POST {url}")
    print(json.dumps(body, indent=2))
    if dry_run:
        print("[DRY RUN] not sent")
        return None
    resp = requests.post(url, json=body, headers=headers, timeout=30)
    print(f"HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text[:500]}
    print(json.dumps(payload, indent=2)[:1200])
    return payload


def _first_id(payload: dict, collection: str, id_field: str):
    """Pull the created id out of a v3 mutation response, or fail loudly."""
    section = (payload or {}).get(collection) or {}
    errors = section.get("error") or []
    successes = section.get("success") or []
    if errors or not successes:
        print(f"\nFAILED: Amazon rejected the {collection} request.")
        sys.exit(1)
    return successes[0].get(id_field)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true",
                    help="actually create it (default is a dry run)")
    ap.add_argument("--country", default="US", help="profile country code")
    args = ap.parse_args()
    dry_run = not args.confirm

    db = SessionLocal()
    try:
        account = db.query(SellerAccount).first()
        if account is None:
            sys.exit("No seller account found.")
        profile = (
            db.query(AdsProfile)
            .filter(AdsProfile.seller_account_id == account.id,
                    AdsProfile.country_code == args.country)
            .one_or_none()
        )
        if profile is None:
            sys.exit(f"No {args.country} profile found.")

        pid = profile.amazon_profile_id
        print(f"Account : {account.name}")
        print(f"Profile : {pid} ({profile.country_code})")
        print(f"Mode    : {'DRY RUN — nothing will be sent' if dry_run else 'LIVE — will create objects'}")

        if not dry_run:
            # Same kill-switch that governs the application.
            assert_write_enabled()

        token = AccountService(db).get_valid_access_token(account)
        base = settings.amazon_api_base_url

        # 1. Campaign — PAUSED, $1/day.
        campaign_body = {"campaigns": [{
            "name": CAMPAIGN_NAME,
            "targetingType": "MANUAL",
            "state": "PAUSED",
            "budget": {"budgetType": "DAILY", "budget": DAILY_BUDGET},
            "startDate": date.today().isoformat(),
            "dynamicBidding": {"strategy": "LEGACY_FOR_SALES"},
        }]}
        payload = _post(f"{base}/sp/campaigns", campaign_body,
                        _headers(token, pid, "application/vnd.spCampaign.v3+json"),
                        "1/3 campaign (PAUSED)", dry_run)
        campaign_id = _first_id(payload, "campaigns", "campaignId") if not dry_run else "<dry-run>"

        # 2. Ad group — no product ads, so it can never serve.
        ad_group_body = {"adGroups": [{
            "name": AD_GROUP_NAME,
            "campaignId": str(campaign_id),
            "state": "PAUSED",
            "defaultBid": BID,
        }]}
        payload = _post(f"{base}/sp/adGroups", ad_group_body,
                        _headers(token, pid, "application/vnd.spAdGroup.v3+json"),
                        "2/3 ad group", dry_run)
        ad_group_id = _first_id(payload, "adGroups", "adGroupId") if not dry_run else "<dry-run>"

        # 3. Keyword — the object whose bid the app will later change.
        keyword_body = {"keywords": [{
            "campaignId": str(campaign_id),
            "adGroupId": str(ad_group_id),
            "keywordText": KEYWORD_TEXT,
            "matchType": "EXACT",
            "state": "ENABLED",
            "bid": BID,
        }]}
        payload = _post(f"{base}/sp/keywords", keyword_body,
                        _headers(token, pid, "application/vnd.spKeyword.v3+json"),
                        "3/3 keyword", dry_run)
        keyword_id = _first_id(payload, "keywords", "keywordId") if not dry_run else "<dry-run>"

        print("\n" + "=" * 60)
        if dry_run:
            print("DRY RUN complete — nothing was created.")
            print("Re-run with --confirm to create it for real.")
        else:
            print("CREATED")
            print(f"  campaign_id : {campaign_id}")
            print(f"  ad_group_id : {ad_group_id}")
            print(f"  keyword_id  : {keyword_id}   (bid ${BID})")
            print("\nNext: run a targets sync so the keyword appears in our database,")
            print("then Plan 3 Task 7 can change this bid and roll it back.")
            print("When finished, archive the campaign in the Amazon console.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
