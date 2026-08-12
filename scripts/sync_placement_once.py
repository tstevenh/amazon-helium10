"""One-off placement performance sync, for verifying the pipeline end to end.

Placement reports take 20-40 minutes to generate, so this exists to be run in
the background rather than inside a request. The scheduled path is
PerformanceService.sync_performance, which does the same thing per profile.
"""
import logging
from datetime import date, timedelta

logging.basicConfig(level=logging.WARNING, format="%(message)s")

from app.core.amazon_reporting import fetch_placement_performance
from app.database import SessionLocal
from app.modules.accounts.repository import AdsProfileRepository, SellerAccountRepository
from app.modules.accounts.service import AccountService
from app.modules.campaigns.models import Campaign
from app.modules.performance.repository import PerformanceRepository

db = SessionLocal()
acct = SellerAccountRepository(db).list_all()[0]
svc = AccountService(db)
repo = PerformanceRepository(db)

end = date.today() - timedelta(days=3)
start = end - timedelta(days=13)

for prof in AdsProfileRepository(db).get_by_account(acct.id):
    camp_map = {
        c.amazon_campaign_id: c
        for c in db.query(Campaign).filter(
            Campaign.profile_id == prof.id, Campaign.deleted_at.is_(None)
        ).all()
    }
    if not camp_map:
        print(f"skip {prof.country_code}: no campaigns")
        continue
    token = svc.get_valid_access_token(acct, force_refresh=True)
    try:
        raw = fetch_placement_performance(
            token, prof.amazon_profile_id, start, end,
            token_getter=lambda: svc.get_valid_access_token(acct, force_refresh=True),
        )
    except Exception as exc:
        print(f"FAILED {prof.country_code}: {exc}")
        continue

    rows = []
    for r in raw:
        camp = camp_map.get(r["amazon_campaign_id"])
        if camp is None:
            continue
        rows.append({
            "campaign_id": str(camp.id), "date": r["date"],
            "placement": r["placement"], "impressions": r["impressions"],
            "clicks": r["clicks"], "spend": r["spend"], "sales": r["sales"],
            "orders": r["orders"], "acos": r["acos"],
        })
    n = repo.upsert_placement_perf(rows)
    print(f"{prof.country_code}: {len(raw)} raw -> {n} rows upserted")

print("DONE")
