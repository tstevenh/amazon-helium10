"""Suggestion engine — negative + harvest (Sprint 2.5 + Sprint 3).

Changes from Sprint 2:
  - Aggregates across ALL ad groups per search_term (deduplication at source).
  - Deduplication key changed to (profile_id, search_term, suggestion_type).
  - Confidence score (0-100) computed and stored per suggestion.
  - Aggregated metrics (campaign_count, ad_group_count, total_spend, total_sales,
    total_orders) stored directly on the suggestion row.
  - Sprint 3: source_type='engine' explicitly set on all engine-generated suggestions.

Rules
-----
NEGATIVE triggers (skip if pending already exists):
  1. cost > 5  AND orders == 0          → negative_exact   "High spend, zero orders"
  2. clicks > 15 AND orders == 0        → negative_phrase  "High clicks, no conversions"
  3. ACOS > 1.5 (150%) AND orders > 0  → negative_exact   "ACOS exceeds 150%"
  4. term starts with "how to|free|diy" → negative_exact   "Non-purchase intent"

HARVEST triggers (skip if pending already exists):
  1. sales > 10 AND ACOS < 0.30        → keyword_exact    "Strong sales, low ACOS"
  2. orders > 1 AND ROAS > 4.0         → keyword_phrase   "High ROAS"
  3. CVR > 0.08 AND clicks > 5         → keyword_broad    "Strong conversion rate"
"""
from __future__ import annotations
import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.search_terms.repository import SearchTermRepository
from app.modules.suggestions.repository import SuggestionRepository

logger = logging.getLogger(__name__)

_NON_PURCHASE_PREFIXES = ("how to", "free", "diy", "what is", "why ", "where to find")


# ── Confidence scoring ─────────────────────────────────────────────────────────

def _confidence_negative(
    cost: float,
    sales: float,
    orders: int,
    clicks: int,
    acos: Optional[float],
    is_non_purchase: bool,
) -> int:
    """Score 0-100 measuring certainty that this term should be negated."""
    score = 0

    # High spend with zero orders is the strongest signal
    if orders == 0:
        if cost >= 20:
            score += 45
        elif cost >= 10:
            score += 35
        elif cost >= 5:
            score += 25
        elif cost >= 2:
            score += 12

        # Click volume adds certainty (wasted clicks)
        if clicks >= 30:
            score += 25
        elif clicks >= 15:
            score += 18
        elif clicks >= 5:
            score += 8

    # Terrible ACOS even with some orders
    if acos is not None and orders > 0:
        if acos >= 2.0:
            score += 35
        elif acos >= 1.5:
            score += 25
        elif acos >= 1.0:
            score += 12

    # Non-purchase intent bonus
    if is_non_purchase:
        score += 20

    return min(100, score)


def _confidence_harvest(
    cost: float,
    sales: float,
    orders: int,
    clicks: int,
    acos: Optional[float],
    roas: Optional[float],
    cvr: float,
) -> int:
    """Score 0-100 measuring certainty that this term should be harvested as a keyword."""
    score = 0

    # Sales volume (revenue actually generated)
    if sales >= 50:
        score += 30
    elif sales >= 20:
        score += 25
    elif sales >= 10:
        score += 20
    elif sales >= 5:
        score += 12

    # ACOS efficiency — lower is better
    if acos is not None:
        if acos <= 0.10:
            score += 35
        elif acos <= 0.20:
            score += 28
        elif acos <= 0.30:
            score += 20
        elif acos <= 0.40:
            score += 10
        elif acos <= 0.50:
            score += 4

    # ROAS
    if roas is not None:
        if roas >= 8:
            score += 20
        elif roas >= 6:
            score += 15
        elif roas >= 4:
            score += 10
        elif roas >= 2:
            score += 5

    # Conversion rate
    if cvr >= 0.15:
        score += 15
    elif cvr >= 0.10:
        score += 10
    elif cvr >= 0.05:
        score += 5

    return min(100, score)


# ── Engine ─────────────────────────────────────────────────────────────────────

class SuggestionEngine:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.st_repo   = SearchTermRepository(db)
        self.sugg_repo = SuggestionRepository(db)

    def generate_for_profile(self, profile_id: uuid.UUID, user_id: uuid.UUID) -> int:
        """Run negative + harvest engines. Returns # new suggestions created."""
        today     = date.today()
        date_from = today - timedelta(days=30)

        # Aggregate ALL ad groups for each search_term into a single row
        rows = self.st_repo.get_aggregated_by_term(
            profile_id=profile_id,
            date_from=date_from,
            date_to=today,
        )

        created = 0
        for row in rows:
            created += self._evaluate(row, profile_id)

        logger.info("[suggestions] generated %d suggestions for profile %s", created, profile_id)
        return created

    def _snap(self, row: dict) -> dict:
        """Build a JSON-serialisable metrics snapshot."""
        return {
            "impressions":      row.get("impressions", 0),
            "clicks":           row.get("clicks", 0),
            "cost":             str(row.get("cost", 0)),
            "sales":            str(row.get("sales", 0)),
            "orders":           row.get("orders", 0),
            "acos":             str(row["acos"]) if row.get("acos") is not None else None,
            "roas":             str(row["roas"]) if row.get("roas") is not None else None,
            "ctr":              str(row.get("ctr", 0)),
            "conversion_rate":  str(row.get("conversion_rate", 0)),
        }

    def _make(
        self,
        row: dict,
        profile_id: uuid.UUID,
        suggestion_type: str,
        kind: str,
        reason: str,
        confidence_score: int,
    ) -> bool:
        """Create suggestion if no pending duplicate exists. Returns True if created."""
        search_term = row["search_term"]

        # Deduplication: (profile_id, search_term, suggestion_type) with status=pending
        if self.sugg_repo.pending_exists(profile_id, search_term, suggestion_type):
            return False

        self.sugg_repo.create(dict(
            profile_id       = profile_id,
            campaign_id      = row.get("campaign_id"),
            ad_group_id      = row.get("ad_group_id"),
            search_term      = search_term,
            suggestion_type  = suggestion_type,
            kind             = kind,
            reason           = reason,
            metrics_snapshot = self._snap(row),
            status           = "pending",
            confidence_score = confidence_score,
            campaign_count   = int(row.get("campaign_count") or 1),
            ad_group_count   = int(row.get("ad_group_count") or 1),
            total_spend      = row.get("cost") or Decimal("0"),
            total_sales      = row.get("sales") or Decimal("0"),
            total_orders     = int(row.get("orders") or 0),
            # Sprint 3: built-in engine always marks source as 'engine'
            source_type      = "engine",
            source_rule_id   = None,
            source_rule_name = None,
        ))
        return True

    def _evaluate(self, row: dict, profile_id: uuid.UUID) -> int:
        created = 0
        cost   = float(row.get("cost")  or 0)
        sales  = float(row.get("sales") or 0)
        orders = int(row.get("orders")  or 0)
        clicks = int(row.get("clicks")  or 0)
        acos   = float(row["acos"]) if row.get("acos") is not None else None
        roas   = float(row["roas"]) if row.get("roas") is not None else None
        cvr    = float(row.get("conversion_rate") or 0)
        term   = row["search_term"].lower().strip()
        is_npi = any(term.startswith(pfx) for pfx in _NON_PURCHASE_PREFIXES)

        # ── Negative rules ────────────────────────────────────────────────
        if cost > 5 and orders == 0:
            conf = _confidence_negative(cost, sales, orders, clicks, acos, is_npi)
            if self._make(row, profile_id, "negative_exact", "negative",
                          f"Spent ${cost:.2f} with zero orders — strong negative signal",
                          conf):
                created += 1

        elif clicks > 15 and orders == 0:
            conf = _confidence_negative(cost, sales, orders, clicks, acos, is_npi)
            if self._make(row, profile_id, "negative_phrase", "negative",
                          f"{clicks} clicks with no conversions",
                          conf):
                created += 1

        if acos is not None and acos > 1.5 and orders > 0:
            conf = _confidence_negative(cost, sales, orders, clicks, acos, is_npi)
            if self._make(row, profile_id, "negative_exact", "negative",
                          f"ACOS {acos*100:.0f}% — far above profitable threshold",
                          conf):
                created += 1

        if is_npi:
            conf = _confidence_negative(cost, sales, orders, clicks, acos, is_npi)
            if self._make(row, profile_id, "negative_exact", "negative",
                          "Non-purchase intent query (informational/freebie)",
                          conf):
                created += 1

        # ── Harvest rules ─────────────────────────────────────────────────
        if sales > 10 and acos is not None and acos < 0.30:
            conf = _confidence_harvest(cost, sales, orders, clicks, acos, roas, cvr)
            if self._make(row, profile_id, "keyword_exact", "harvest",
                          f"Strong sales ${sales:.2f} with ACOS {acos*100:.1f}% — add as Exact",
                          conf):
                created += 1

        if orders > 1 and roas is not None and roas > 4.0:
            conf = _confidence_harvest(cost, sales, orders, clicks, acos, roas, cvr)
            if self._make(row, profile_id, "keyword_phrase", "harvest",
                          f"ROAS {roas:.2f}× with {orders} orders — add as Phrase",
                          conf):
                created += 1

        if cvr > 0.08 and clicks > 5:
            conf = _confidence_harvest(cost, sales, orders, clicks, acos, roas, cvr)
            if self._make(row, profile_id, "keyword_broad", "harvest",
                          f"CVR {cvr*100:.1f}% — high conversion rate, add as Broad",
                          conf):
                created += 1

        return created
