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
from app.modules.suggestions.models import Suggestion
from app.modules.suggestions.repository import SuggestionRepository
from app.modules.suggestions.asin import asin_safe_suggestion_type
from app.modules.campaigns.models import Campaign, Target
from app.modules.rules.models import Rule, RuleAdGroupScope, RuleCampaignScope
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
            # Ad-group scope narrows within the campaign scope. Only search-term
            # rules can honour it: budgets and placements are campaign-level, so
            # the API refuses the combination rather than ignoring it here.
            scoped_ad_groups = [
                r.ad_group_id for r in self.db.query(RuleAdGroupScope)
                .filter(RuleAdGroupScope.rule_id == rule.id).all()
            ]
            # Budget rules operate on campaign totals, not on search terms:
            # a budget belongs to a campaign, and no search term has one.
            if rule.rule_type == "budget":
                rows = self._campaign_rows(rule, date_from, scoped_ids)
            elif rule.rule_type == "placement":
                rows = self._placement_rows(rule, date_from, scoped_ids)
            else:
                rows = self.st_repo.get_aggregated_by_term(
                    profile_id   = rule.profile_id,
                    date_from    = date_from,
                    date_to      = date.today(),
                    campaign_ids = scoped_ids or None,
                    ad_group_ids = scoped_ad_groups or None,
                )
            if scoped_ids or scoped_ad_groups:
                logger.info("[rules] rule=%s scoped to %d campaigns, %d ad groups",
                            rule.id, len(scoped_ids), len(scoped_ad_groups))

            rows_evaluated = len(rows)
            created_count  = 0

            for row in rows:
                if self._matches(row, conds, logic):
                    if rule.rule_type == "budget":
                        made = self._make_budget_suggestion(row, rule, sugg_type, action)
                    elif rule.rule_type == "placement":
                        made = self._make_placement_suggestion(row, rule, sugg_type, action)
                    else:
                        made = self._make_suggestion(row, rule, sugg_type, action)
                    if made:
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

    # ── Budget rules ───────────────────────────────────────────────────────

    _BUDGET_TYPES = {"budget_increase", "budget_decrease"}

    # Spec, verified from Adtomic: skip campaigns under 3 days old. Amazon needs
    # roughly 72 hours before a new campaign's numbers mean anything, and a
    # budget cut based on day-one data would strangle a campaign before it had
    # a chance to perform.
    _NEW_CAMPAIGN_GRACE_DAYS = 3

    def _campaign_rows(
        self, rule: Rule, date_from: date, scoped_ids: list
    ) -> list[dict]:
        """Campaign totals over the lookback window, shaped like a rule row.

        Returns the same keys _matches() reads for search terms, so one
        condition evaluator serves both. `search_term` carries the campaign
        name because suggestions.search_term is NOT NULL and the campaign name
        is what the operator needs to see on the row.
        """
        from app.modules.performance.repository import PerformanceRepository

        campaigns = (
            self.db.query(Campaign)
            .filter(Campaign.profile_id == rule.profile_id,
                    Campaign.deleted_at.is_(None))
            .all()
        )
        if scoped_ids:
            wanted = set(scoped_ids)
            campaigns = [c for c in campaigns if c.id in wanted]

        cutoff = date.today() - timedelta(days=self._NEW_CAMPAIGN_GRACE_DAYS)
        eligible = []
        for c in campaigns:
            # start_date is Amazon's; created_at is ours. Prefer Amazon's, and
            # fall back to when we first saw the campaign.
            began = c.start_date or (c.created_at.date() if c.created_at else None)
            if began is not None and began > cutoff:
                logger.info(
                    "[rules] skipping campaign %s — started %s, inside the "
                    "%d-day grace window",
                    c.name, began, self._NEW_CAMPAIGN_GRACE_DAYS,
                )
                continue
            eligible.append(c)

        if not eligible:
            return []

        metrics = PerformanceRepository(self.db).get_all_campaigns_summary(
            [str(c.id) for c in eligible], date_from, date.today(),
        )

        rows: list[dict] = []
        for c in eligible:
            m = metrics.get(str(c.id))
            if not m:
                # No performance rows in the window: nothing to reason about.
                continue
            rows.append({
                "campaign_id":     c.id,
                "ad_group_id":     None,
                "search_term":     c.name,
                "impressions":     m["impressions"],
                "clicks":          m["clicks"],
                "cost":            m["spend"],
                "sales":           m["sales"],
                "orders":          m["orders"],
                # UNIT TRAP: rule rows carry acos as a RATIO (0.577), because
                # _field_value multiplies _PERCENT_FIELDS by 100 for comparison
                # against the user's "40" meaning 40%. SearchTermRepository
                # returns a ratio; PerformanceRepository returns a PERCENTAGE
                # for acos while returning a ratio for ctr — inconsistent within
                # the same function. Converting here keeps one convention in the
                # engine.
                #
                # Without this, "ACOS > 40" evaluated as "ACOS > 0.4%" and
                # matched a campaign running at 24% real ACOS, i.e. it proposed
                # cutting the budget of a profitable campaign.
                "acos":            (Decimal(str(m["acos"])) / 100
                                    if m["acos"] is not None else None),
                "roas":            m["roas"],
                "ctr":             m["ctr"] or 0,
                "conversion_rate": (
                    Decimal(m["orders"]) / Decimal(m["clicks"])
                    if m["clicks"] else Decimal(0)
                ),
                "campaign_count":  1,
                "ad_group_count":  1,
                "_campaign":       c,
            })
        return rows

    def _resolve_budget_change(
        self, row: dict, suggestion_type: str, action: Optional[dict]
    ) -> Optional[tuple]:
        """Returns (campaign, current_budget, new_budget) or None to skip."""
        if suggestion_type not in self._BUDGET_TYPES:
            return None
        campaign = row.get("_campaign")
        if campaign is None or campaign.daily_budget is None:
            return None

        pct = float((action or {}).get("percent", 20))
        current = float(campaign.daily_budget)
        if suggestion_type == "budget_increase":
            new_budget = current * (1 + pct / 100.0)
        else:
            new_budget = current * (1 - pct / 100.0)
        new_budget = round(new_budget, 2)

        # Amazon's SP daily-budget floor. Below it the write would be rejected,
        # so skip rather than create a suggestion guaranteed to fail.
        if new_budget < 1.00:
            return None
        # A change too small to matter is noise in the inbox.
        if abs(new_budget - current) < 0.01:
            return None

        return campaign, current, new_budget

    def _make_budget_suggestion(
        self,
        row: dict,
        rule: Rule,
        suggestion_type: str,
        action: Optional[dict],
    ) -> bool:
        """Create one budget suggestion per campaign, if none is pending.

        Uniqueness is enforced in the database too — see migration 020. Without
        it a daily evaluation would stack a new suggestion every day, each
        proposing a change from the ORIGINAL budget, so approving two would
        compound into a change nobody intended.
        """
        resolved = self._resolve_budget_change(row, suggestion_type, action)
        if resolved is None:
            return False
        campaign, current, new_budget = resolved

        # Two constraints guard this row, and BOTH must be checked here or the
        # insert raises IntegrityError and kills the whole rule run:
        #
        #   uq_suggestions_pending_budget_per_campaign (source_rule_id, campaign_id)
        #     — the spec's rule, stops one rule stacking daily suggestions.
        #   uq_suggestion_pending_profile_term_type (profile_id, search_term,
        #     suggestion_type) — pre-existing, and for budget rows search_term
        #     is the campaign name, so it also stops TWO DIFFERENT rules both
        #     proposing a budget change to the same campaign.
        #
        # The second is stricter and desirable: two pending cuts on one campaign
        # would compound if both were approved. Found by running two rules
        # against the same campaign and watching the run fail.
        same_rule = (
            self.db.query(Suggestion)
            .filter(
                Suggestion.source_rule_id == rule.id,
                Suggestion.campaign_id == campaign.id,
                Suggestion.suggestion_type == suggestion_type,
                Suggestion.status == "pending",
            )
            .first()
        )
        if same_rule is not None:
            return False

        if self.sugg_repo.pending_exists(
            rule.profile_id, campaign.name, suggestion_type
        ):
            logger.info(
                "[rules] campaign %s already has a pending %s from another rule",
                campaign.name, suggestion_type,
            )
            return False

        config = rule.configuration_json or {}
        conds  = config.get("conditions", [])
        logic  = config.get("logic", "AND")
        reason = self._build_reason(rule, action, row)
        direction = "raise" if suggestion_type == "budget_increase" else "lower"
        reason = (
            f"{reason} — {direction} daily budget ${current:.2f} → ${new_budget:.2f}"
            if reason else
            f"{direction} daily budget ${current:.2f} → ${new_budget:.2f}"
        )

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
            campaign_id      = campaign.id,
            ad_group_id      = None,
            search_term      = campaign.name,
            target_id        = None,
            current_value    = {"budget": current},
            suggested_value  = {"budget": new_budget},
            suggestion_type  = suggestion_type,
            kind             = "budget",
            reason           = reason,
            metrics_snapshot = snap,
            status           = "pending",
            confidence_score = _rule_confidence(row, conds, logic),
            campaign_count   = 1,
            ad_group_count   = 1,
            total_spend      = row.get("cost")  or Decimal("0"),
            total_sales      = row.get("sales") or Decimal("0"),
            total_orders     = int(row.get("orders") or 0),
            source_type      = "rule",
            source_rule_id   = rule.id,
            source_rule_name = rule.name,
        ))
        return True

    # ── Placement rules ────────────────────────────────────────────────────
    #
    # Amazon lets you bid a PERCENTAGE UPLIFT per placement (0-900), not an
    # absolute bid. So a placement suggestion changes a multiplier, and the
    # meaningful unit is percentage POINTS: "top of search 0% -> 25%".
    #
    # The multipliers live on campaigns.placement_bidding, synced from Amazon.
    # A campaign we have never seen adjustments for is treated as 0 across the
    # board, which is Amazon's default.

    _PLACEMENT_TYPES = {"placement_increase", "placement_decrease"}

    # Only these three can carry an adjustment. 'other' exists in the
    # performance table for rows Amazon sent without a label, and must never
    # become a suggestion — there is no placement to adjust.
    _ADJUSTABLE_PLACEMENTS = ("top_of_search", "product_pages", "rest_of_search")

    # Amazon's ceiling.
    _MAX_PLACEMENT_ADJUSTMENT = 900

    _PLACEMENT_LABELS = {
        "top_of_search": "Top of search",
        "product_pages": "Product pages",
        "rest_of_search": "Rest of search",
    }

    @staticmethod
    def current_placement_adjustments(campaign) -> dict[str, float]:
        """Adjustments currently set on Amazon, defaulting to 0.

        placement_bidding is stored as Amazon returns it, which may be a list of
        {placement, percentage} or a dict. Both shapes are accepted because this
        is synced data and Amazon has changed it before.
        """
        raw = getattr(campaign, "placement_bidding", None)
        out = {p: 0.0 for p in RuleEngine._ADJUSTABLE_PLACEMENTS}
        if not raw:
            return out

        amazon_to_ours = {
            "PLACEMENT_TOP": "top_of_search",
            "PLACEMENT_PRODUCT_PAGE": "product_pages",
            "PLACEMENT_REST_OF_SEARCH": "rest_of_search",
        }

        entries = raw if isinstance(raw, list) else raw.get("placementBidding", [])
        if isinstance(entries, dict):
            entries = [{"placement": k, "percentage": v} for k, v in entries.items()]
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            name = amazon_to_ours.get(e.get("placement"), e.get("placement"))
            if name in out:
                try:
                    out[name] = float(e.get("percentage") or 0)
                except (TypeError, ValueError):
                    continue
        return out

    def _placement_rows(
        self, rule: Rule, date_from: date, scoped_ids: list
    ) -> list[dict]:
        """One row per campaign x placement, shaped like any other rule row."""
        from app.modules.performance.repository import PerformanceRepository

        campaigns = (
            self.db.query(Campaign)
            .filter(Campaign.profile_id == rule.profile_id,
                    Campaign.deleted_at.is_(None))
            .all()
        )
        if scoped_ids:
            wanted = set(scoped_ids)
            campaigns = [c for c in campaigns if c.id in wanted]
        if not campaigns:
            return []

        by_campaign = PerformanceRepository(self.db).placement_summary(
            [str(c.id) for c in campaigns], date_from, date.today(),
        )

        rows: list[dict] = []
        for c in campaigns:
            placements = by_campaign.get(str(c.id)) or {}
            for placement, m in placements.items():
                if placement not in self._ADJUSTABLE_PLACEMENTS:
                    continue
                rows.append({
                    "campaign_id":     c.id,
                    "ad_group_id":     None,
                    # placement_summary already returns acos as a RATIO, unlike
                    # get_all_campaigns_summary — see the 100x unit bug in
                    # tests/modules/test_budget_rules.py. No conversion here.
                    "acos":            m["acos"],
                    "roas":            m["roas"],
                    "search_term":     f"{c.name} · {self._PLACEMENT_LABELS[placement]}",
                    "impressions":     m["impressions"],
                    "clicks":          m["clicks"],
                    "cost":            Decimal(str(m["spend"])),
                    "sales":           Decimal(str(m["sales"])),
                    "orders":          m["orders"],
                    "ctr":             (Decimal(m["clicks"]) / Decimal(m["impressions"])
                                        if m["impressions"] else Decimal(0)),
                    "conversion_rate": (Decimal(m["orders"]) / Decimal(m["clicks"])
                                        if m["clicks"] else Decimal(0)),
                    "campaign_count":  1,
                    "ad_group_count":  1,
                    "_campaign":       c,
                    "_placement":      placement,
                })
        return rows

    def _resolve_placement_change(
        self, row: dict, suggestion_type: str, action: Optional[dict]
    ) -> Optional[tuple]:
        """Returns (campaign, placement, current_pct, new_pct) or None."""
        if suggestion_type not in self._PLACEMENT_TYPES:
            return None
        campaign = row.get("_campaign")
        placement = row.get("_placement")
        if campaign is None or placement not in self._ADJUSTABLE_PLACEMENTS:
            return None

        points = float((action or {}).get("percent", 20))
        current = self.current_placement_adjustments(campaign)[placement]

        # Percentage POINTS, not a percentage of the current value: going from
        # 0% by "20% of 0" would never move, and Amazon's own UI works in points.
        new_pct = current + points if suggestion_type == "placement_increase" \
            else current - points
        new_pct = round(max(0.0, min(float(self._MAX_PLACEMENT_ADJUSTMENT), new_pct)), 2)

        # Already at the floor or ceiling: nothing to suggest.
        if abs(new_pct - current) < 0.01:
            return None

        return campaign, placement, current, new_pct

    def _make_placement_suggestion(
        self,
        row: dict,
        rule: Rule,
        suggestion_type: str,
        action: Optional[dict],
    ) -> bool:
        resolved = self._resolve_placement_change(row, suggestion_type, action)
        if resolved is None:
            return False
        campaign, placement, current, new_pct = resolved

        # search_term is "Campaign · Placement", so the pre-existing
        # uq_suggestion_pending_profile_term_type index gives us one pending
        # suggestion per campaign per placement for free.
        if self.sugg_repo.pending_exists(
            rule.profile_id, row["search_term"], suggestion_type
        ):
            return False

        config = rule.configuration_json or {}
        conds  = config.get("conditions", [])
        logic  = config.get("logic", "AND")
        verb   = "raise" if suggestion_type == "placement_increase" else "lower"
        reason = self._build_reason(rule, action, row)
        reason = (
            f"{reason} — {verb} {self._PLACEMENT_LABELS[placement]} bid adjustment "
            f"{current:.0f}% → {new_pct:.0f}%"
            if reason else
            f"{verb} {self._PLACEMENT_LABELS[placement]} bid adjustment "
            f"{current:.0f}% → {new_pct:.0f}%"
        )

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
            campaign_id      = campaign.id,
            ad_group_id      = None,
            search_term      = row["search_term"],
            target_id        = None,
            # The executor needs the placement name AND the full current set,
            # because Amazon replaces the placementBidding array wholesale.
            current_value    = {"placement": placement, "adjustment": current,
                                "all_adjustments": self.current_placement_adjustments(campaign)},
            suggested_value  = {"placement": placement, "adjustment": new_pct},
            suggestion_type  = suggestion_type,
            kind             = "placement",
            reason           = reason,
            metrics_snapshot = snap,
            status           = "pending",
            confidence_score = _rule_confidence(row, conds, logic),
            campaign_count   = 1,
            ad_group_count   = 1,
            total_spend      = row.get("cost")  or Decimal("0"),
            total_sales      = row.get("sales") or Decimal("0"),
            total_orders     = int(row.get("orders") or 0),
            source_type      = "rule",
            source_rule_id   = rule.id,
            source_rule_name = rule.name,
        ))
        return True

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
