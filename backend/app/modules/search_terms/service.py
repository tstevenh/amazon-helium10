"""Search term sync service with mock data (Sprint 2)."""
from __future__ import annotations
import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.modules.accounts.models import AdsProfile, SellerAccount
from app.modules.accounts.repository import AdsProfileRepository
from app.modules.campaigns.models import AdGroup, Campaign
from app.modules.search_terms.repository import SearchTermRepository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mock search-term data per marketplace (country_code)
# Format: (search_term, impressions, clicks, cost, sales, orders, units)
# ---------------------------------------------------------------------------

_US_AUTO_TERMS: list[tuple] = [
    # Good terms → harvest candidates (ACOS < 30%)
    ("organic coffee beans 1lb",         850,  85,  42.50,  168.00, 12, 12),
    ("dark roast ground coffee",         1200, 120,  67.20,  252.00, 18, 18),
    ("single origin coffee beans",        650,  65,  31.50,  140.00, 10, 10),
    ("arabica coffee whole bean",          450,  45,  22.40,  112.00,  8,  8),
    ("fresh roasted coffee online",        520,  52,  25.90,  126.00,  9,  9),
    ("light roast coffee bag",             300,  30,  15.00,   70.00,  5,  5),
    # Bad terms → negative candidates (spend > $5, orders = 0)
    ("coffee table furniture",             450,  45,  22.50,    0.00,  0,  0),
    ("how to make cold brew coffee",       280,  28,  14.00,    0.00,  0,  0),
    ("free coffee samples online",         350,  35,  17.50,    0.00,  0,  0),
    ("coffee mug with lid",                420,  42,  21.00,    0.00,  0,  0),
    ("instant coffee packets singles",     250,  25,  12.50,    0.00,  0,  0),
    ("coffee maker machine automatic",     380,  38,  19.00,    0.00,  0,  0),
    # Competitor brand terms → high ACOS
    ("starbucks dark roast coffee pods",   620,  62,  37.20,   22.00,  2,  2),
    ("nescafe gold instant coffee",        310,  31,  18.60,    8.00,  1,  1),
    ("death wish coffee whole bean",       380,  38,  22.80,   10.00,  1,  1),
    # Borderline (ACOS 40-60%)
    ("coffee gift set holiday box",        380,  38,  19.00,   39.00,  3,  3),
    ("gourmet coffee subscription box",    320,  32,  19.20,   42.00,  3,  3),
    ("specialty coffee sampler pack",      290,  29,  17.40,   36.40,  2,  2),
]

_US_BRAND_TERMS: list[tuple] = [
    # Brand terms (very low ACOS — user's own brand)
    ("ppc os coffee brand",               200,  20,   6.00,   56.00,  4,  4),
    ("ppc os organic coffee",             150,  15,   4.50,   42.00,  3,  3),
    ("ppc os dark roast",                 180,  18,   5.40,   50.40,  4,  4),
]

_CA_AUTO_TERMS: list[tuple] = [
    # Good CA terms
    ("organic coffee canada",              340,  34,  17.00,   67.20,  4,  4),
    ("dark roast coffee beans canada",     280,  28,  14.00,   56.00,  4,  4),
    ("specialty coffee ontario",           220,  22,  11.00,   44.00,  3,  3),
    # Bad CA terms
    ("tim hortons coffee pods",            320,  32,  16.00,    0.00,  0,  0),
    ("canadian coffee table",              280,  28,  14.00,    0.00,  0,  0),
    ("how to roast coffee at home",        180,  18,   9.00,    0.00,  0,  0),
    # Borderline CA
    ("coffee gift set canada",             240,  24,  12.00,   25.20,  2,  2),
]

_CA_BRAND_TERMS: list[tuple] = [
    ("ppc os coffee canada",              120,  12,   3.60,   33.60,  3,  3),
    ("ppc os arabica canada",              90,   9,   2.70,   25.20,  2,  2),
]


def _compute_metrics(clicks: int, cost: float, sales: float, orders: int, impressions: int) -> dict:
    cost_d = Decimal(str(cost))
    sales_d = Decimal(str(sales))
    ctr = Decimal(str(round(clicks / impressions, 6))) if impressions else Decimal("0")
    cpc = Decimal(str(round(cost / clicks, 4))) if clicks else Decimal("0")
    acos = Decimal(str(round(cost / sales, 6))) if sales else None
    roas = Decimal(str(round(sales / cost, 4))) if cost else None
    cvr = Decimal(str(round(orders / clicks, 6))) if clicks else Decimal("0")
    return dict(ctr=ctr, cpc=cpc, acos=acos, roas=roas, conversion_rate=cvr,
                cost=cost_d, sales=sales_d)


class SearchTermSyncService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = SearchTermRepository(db)
        self.profile_repo = AdsProfileRepository(db)

    def sync_for_account(self, account: SellerAccount) -> dict:
        """Sync search terms for all profiles of an account."""
        profiles = self.profile_repo.get_by_account(account.id)
        total = 0
        for profile in profiles:
            total += self._sync_profile(profile)
        self.db.commit()
        return {"terms_synced": total}

    def _sync_profile(self, profile: AdsProfile) -> int:
        """Generate and upsert mock search terms for one profile."""
        if not settings.amazon_mock_mode:
            logger.warning("Real Amazon Search Term API not implemented; skipping profile %s", profile.id)
            return 0

        # Pick terms by country_code
        country = (profile.country_code or "US").upper()
        sync_date = date.today() - timedelta(days=1)

        # Get this profile's campaigns and ad_groups
        campaigns = (
            self.db.query(Campaign)
            .filter(Campaign.profile_id == profile.id, Campaign.deleted_at.is_(None))
            .all()
        )

        total = 0
        for campaign in campaigns:
            ad_groups = (
                self.db.query(AdGroup)
                .filter(AdGroup.campaign_id == campaign.id, AdGroup.deleted_at.is_(None))
                .all()
            )
            for ag in ad_groups:
                # Choose term set
                is_auto = (campaign.targeting_type or "").lower() == "auto"
                if country == "CA":
                    terms = _CA_AUTO_TERMS if is_auto else _CA_BRAND_TERMS
                else:
                    terms = _US_AUTO_TERMS if is_auto else _US_BRAND_TERMS

                for (term, impr, clicks, cost, sales, orders, units) in terms:
                    metrics = _compute_metrics(clicks, cost, sales, orders, impr)
                    record = dict(
                        profile_id=profile.id,
                        campaign_id=campaign.id,
                        ad_group_id=ag.id,
                        search_term=term,
                        date=sync_date,
                        impressions=impr,
                        clicks=clicks,
                        orders=orders,
                        units=units,
                        last_synced_at=None,
                        **metrics,
                    )
                    self.repo.upsert(record)
                    total += 1

        logger.info("[search_terms] synced %d terms for profile %s (mock)", total, profile.id)
        return total
