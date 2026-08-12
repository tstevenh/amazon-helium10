"""Rule Execution Engine (Sprint 3).

Rules NEVER modify Amazon Ads directly.
Rules ONLY create Suggestions. Human approval is mandatory.

Supported rule types:
  negative  → negative_exact / negative_phrase suggestions
  harvest   → keyword_exact / keyword_phrase / keyword_broad suggestions
  bid       → bid_decrease / bid_increase suggestions

Configuration JSON schema:
  {
    "conditions": [
      {"field": "acos", "operator": "gt", "value": 30}
    ],
    "logic": "AND",              # AND = all must match; OR = any must match
    "suggestion_type": "bid_decrease",
    "lookback_days": 30,
    "action": {"type": "decrease_by_percent", "percent": 10}   # bid rules only
  }

Available fields (from get_aggregated_by_term):
  cost             → total spend in dollars (NOT "spend")
  sales            → total revenue in dollars
  orders           → total order count (integer)
  clicks           → total click count
  impressions      → total impression count
  acos             → cost/sales as percentage (30 = 30%)  — NULL if no sales
  roas             → sales/cost ratio (4.0 = 4x)          — NULL if no spend
  ctr              → clicks/impressions as percentage
  conversion_rate  → orders/clicks as percentage
  cpc              → cost per click in dollars

Operator codes accepted (both string codes and symbols):
  "gt" / ">"   → greater than
  "gte" / ">=" → greater than or equal
  "lt" / "<"   → less than
  "lte" / "<=" → less than or equal
  "eq" / "=="  → equal
  "neq" / "!=" → not equal
"""
from __future__ import annotations
import logging
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.search_terms.repository import SearchTermRepository
from app.modules.suggestions.repository import SuggestionRepository
from app.modules.suggestions.asin import asin_safe_suggestion_type
from app.modules.campaigns.models import Target
from app.modules.rules.models import Rule, RuleCampaignScope
from app.modules.rules.repository import RuleExecutionRepository

logger = logging.getLogger(__name__)

# DB stores these as ratios (0.30); config stores as percentages (30.0)
_PERCENT_FIELDS = {"acos", "ctr", "conversion_rate"}

# Map symbolic operators to code strings
_OP_ALIASES: dict[str, str] = {
    ">":  "gt",
    ">=": "gte",
    "<":  "lt",
    "<=": "lte",
    "==": "eq",
    "!=": "neq",
}


def _normalize_op(op: str) -> str:
    """Convert symbolic operators (>, >=, etc.) to code strings (gt, gte, etc.)."""
    return _OP_ALIASES.get(op, op)


def _field_value(row: dict, field: str) -> Optional[float]:
    """Extract field value, converting ratio-stored fields to percentage."""
    val = row.get(field)
    if val is None:
        return None
    fval = float(val)
    if field in _PERCENT_FIELDS:
        fval = fval * 100.0   # 0.30 → 30.0 for user-facing comparison
    return fval


def _eval_cond(actual: Optional[float], op: str, threshold: float) -> bool:
    op = _normalize_op(op)
    if actual is None:
        return False
    if op == "gt":  return actual >  threshold
    if op == "gte": return actual >= threshold
    if op == "lt":  return actual <  threshold
    if op == "lte": return actual <= threshold
    if op == "eq":  return abs(actual - threshold) < 1e-9
    if op == "neq": return abs(actual - threshold) >= 1e-9
    return False


def _rule_confidence(row: dict, conditions: list[dict], logic: str) -> int:
    """Score 0-100 based on how strongly conditions are satisfied.

    Base: 50.  Each condition can add up to (50 / num_conditions) more
    proportional to how far the actual value exceeds the threshold.
    """
    if not conditions:
        return 50
    score = 50
    bonus_per = max(5, 50 // len(conditions))

    for cond in conditions:
        field     = cond.get("field", "")
        op        = _normalize_op(cond.get("operator", "gt"))
        threshold = float(cond.get("value", 0))
        actual    = _field_value(row, field)
        if actual is None or threshold == 0:
            continue
        if op in ("gt", "gte") and actual > threshold:
            excess = min(1.0, (actual - threshold) / threshold)
            score += int(bonus_per * excess)
        elif op in ("lt", "lte") and actual < threshold:
            below = min(1.0, (threshold - actual) / threshold)
            score += int(bonus_per * below)
        elif op in ("eq", "neq"):
            score += bonus_per // 2

    return min(100, score)


class RuleEngine:
    def __init__(self, db: Session) -> None:
        self.db        = db
        self.st_repo   = SearchTermRepository(db)
        self.sugg_repo = SuggestionRepository(db)
        self.exec_repo = RuleExecutionRepository(db)

    # ── Public API ─────────────────────────────────────────────────────────

    def execute(self, rule: Rule, user_id: uuid.UUID) -> dict:
        """
        Evaluate rule against search terms for its profile.
        Creates Suggestions only — never touches Amazon Ads.
        Returns execution summary dict.
        """
        t0       = time.monotonic()
        exec_rec = self.exec_repo.create(rule.id, rule.profile_id)

        try:
            config    = rule.configuration_json or {}
            conds     = config.get("conditions", [])
            logic     = config.get("logic", "AND")
            lookback  = int(config.get("lookback_days", 30))
            sugg_type = config.get("suggestion_type", "")
            action    = config.get("action")

            date_from = date.today() - timedelta(days=lookback)
            # Scope to specific campaigns when the rule defines any; no rows
            # in rule_campaign_scope means profile-wide.
            scoped_ids = [
                r.campaign_id for r in self.db.query(RuleCampaignScope)
                .filter(RuleCampaignScope.rule_id == rule.id).all()
            ]
            rows      = self.st_repo.get_aggregated_by_term(
                profile_id   = rule.profile_id,
                date_from    = date_from,
                date_to      = date.today(),
                campaign_ids = scoped_ids or None,
            )
            if scoped_ids:
                logger.info("[rules] rule=%s scoped to %d campaigns", rule.id, len(scoped_ids))

            rows_evaluated = len(rows)
            created_count  = 0

            for row in rows:
                if self._matches(row, conds, logic):
                    if self._make_suggestion(row, rule, sugg_type, action):
                        created_count += 1

            exec_rec = self.exec_repo.complete(
                exec_rec.id,
                rows_evaluated       = rows_evaluated,
                suggestions_generated = created_count,
            )

            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "[rules] rule=%s rows=%d suggestions=%d duration=%dms",
                rule.id, rows_evaluated, created_count, duration_ms,
            )
            return {
                "rule_id":               str(rule.id),
                "rule_name":             rule.name,
                "execution_id":          str(exec_rec.id),
                "rows_evaluated":        rows_evaluated,
                "suggestions_generated": created_count,
                "execution_status":      "completed",
                "duration_ms":           duration_ms,
            }

        except Exception as exc:
            self.exec_repo.fail(exec_rec.id, str(exc))
            logger.exception("[rules] execution failed for rule %s", rule.id)
            raise

    # ── Private helpers ────────────────────────────────────────────────────

    def _matches(self, row: dict, conds: list[dict], logic: str) -> bool:
        if not conds:
            return False
        results = [
            _eval_cond(
                _field_value(row, c.get("field", "")),
                c.get("operator", "gt"),
                float(c.get("value", 0)),
            )
            for c in conds
        ]
        return all(results) if logic == "AND" else any(results)

    # ── Bid resolution ─────────────────────────────────────────────────────

    _BID_TYPES = {"bid_increase", "bid_decrease", "bid_change"}

    def _resolve_bid_change(
        self, row: dict, suggestion_type: str, action: Optional[dict]
    ) -> Optional[tuple]:
        """For a bid suggestion, find the keyword to change and the new bid.

        Returns (target, current_bid, new_bid) or None when the change cannot
        be expressed — in which case no suggestion is created at all.

        A bid rule evaluated over search terms only makes sense when the
        search term IS a keyword you are already bidding on: that is the
        object whose bid can be changed. A search term with no matching
        keyword has nothing to act on, so it is skipped rather than turned
        into a suggestion the execution job would later reject.
        """
        if suggestion_type not in self._BID_TYPES:
            return None

        ad_group_id = row.get("ad_group_id")
        term = (row.get("search_term") or "").strip().lower()
        if not ad_group_id or not term:
            return None

        target = (
            self.db.query(Target)
            .filter(
                Target.ad_group_id == ad_group_id,
                Target.target_kind == "keyword",
                Target.deleted_at.is_(None),
                func.lower(Target.expression_text) == term,
            )
            .first()
        )
        if target is None or target.bid is None:
            return None

        pct = float((action or {}).get("percent", 10))
        current = float(target.bid)
        if suggestion_type == "bid_increase":
            new_bid = current * (1 + pct / 100.0)
        else:
            new_bid = current * (1 - pct / 100.0)

        # Amazon rejects bids below its floor; skip rather than create a
        # suggestion that is guaranteed to fail on execution.
        new_bid = round(new_bid, 2)
        if new_bid <= 0.02:
            return None

        return target, current, new_bid

    def _make_suggestion(
        self,
        row: dict,
        rule: Rule,
        suggestion_type: str,
        action: Optional[dict],
    ) -> bool:
        """Create suggestion if no pending duplicate. Returns True if created."""
        search_term = row["search_term"]

        # An ASIN search term is a product-targeting placement, so a keyword-
        # typed suggestion for it is unactionable — Amazon accepts neither a
        # positive nor a negative keyword for an ASIN. Applied here as well as
        # in SuggestionEngine because both engines create suggestions, and
        # fixing only one left this path still producing bad rows.
        suggestion_type = asin_safe_suggestion_type(search_term, suggestion_type)

        if self.sugg_repo.pending_exists(rule.profile_id, search_term, suggestion_type):
            return False

        config  = rule.configuration_json or {}
        conds   = config.get("conditions", [])
        logic   = config.get("logic", "AND")
        conf    = _rule_confidence(row, conds, logic)
        kind    = self._kind_for_type(suggestion_type)
        reason  = self._build_reason(rule, action, row)

        # A bid suggestion must carry the target and both values, or the
        # execution job has nothing machine-readable to act on. This was the
        # gap that made execution impossible in the first place.
        target_id = current_value = suggested_value = None
        if suggestion_type in self._BID_TYPES:
            resolved = self._resolve_bid_change(row, suggestion_type, action)
            if resolved is None:
                return False
            target, current_bid, new_bid = resolved
            target_id       = target.id
            current_value   = {"bid": current_bid}
            suggested_value = {"bid": new_bid}
            reason = (f"{reason} — bid ${current_bid:.2f} → ${new_bid:.2f}"
                      if reason else f"bid ${current_bid:.2f} → ${new_bid:.2f}")

        snap = {
            "impressions":     row.get("impressions", 0),
            "clicks":          row.get("clicks", 0),
            "cost":            str(row.get("cost", 0)),
            "sales":           str(row.get("sales", 0)),
            "orders":          row.get("orders", 0),
            "acos":            str(row["acos"]) if row.get("acos") is not None else None,
            "roas":            str(row["roas"]) if row.get("roas") is not None else None,
            "ctr":             str(row.get("ctr", 0)),
            "conversion_rate": str(row.get("conversion_rate", 0)),
        }

        self.sugg_repo.create(dict(
            profile_id       = rule.profile_id,
            campaign_id      = row.get("campaign_id"),
            ad_group_id      = row.get("ad_group_id"),
            search_term      = search_term,
            target_id        = target_id,
            current_value    = current_value,
            suggested_value  = suggested_value,
            suggestion_type  = suggestion_type,
            kind             = kind,
            reason           = reason,
            metrics_snapshot = snap,
            status           = "pending",
            confidence_score = conf,
            campaign_count   = int(row.get("campaign_count") or 1),
            ad_group_count   = int(row.get("ad_group_count") or 1),
            total_spend      = row.get("cost")   or Decimal("0"),
            total_sales      = row.get("sales")  or Decimal("0"),
            total_orders     = int(row.get("orders") or 0),
            source_type      = "rule",
            source_rule_id   = rule.id,
            source_rule_name = rule.name,
        ))
        return True

    @staticmethod
    def _kind_for_type(suggestion_type: str) -> str:
        if suggestion_type.startswith("negative"):
            return "negative"
        if suggestion_type.startswith("keyword"):
            return "harvest"
        if suggestion_type.startswith("bid"):
            return "bid"
        return "harvest"

    @staticmethod
    def _build_reason(rule: Rule, action: Optional[dict], row: dict) -> str:
        base = f'Rule "{rule.name}"'
        if action:
            t   = action.get("type", "")
            pct = action.get("percent", 0)
            if t == "decrease_by_percent":
                return f'{base}: decrease bid by {pct}%'
            if t == "increase_by_percent":
                return f'{base}: increase bid by {pct}%'
        return f'{base}: matched {rule.rule_type} conditions'
