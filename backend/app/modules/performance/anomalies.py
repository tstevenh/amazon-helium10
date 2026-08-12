"""Anomaly detection for the Dashboard panel (spec §13.1, Phase 3).

The spec's mockup is concrete about what an anomaly row looks like:

    Seller A/US "Sandals Auto" spend +340%   [Review]
    Seller C/UK Budget exhausted by 11am, 3d run..   [Review]

so this detects *changes worth a human's attention*, not threshold breaches.
A campaign that has always run at 60% ACoS is not an anomaly — it is a
standing decision. A campaign that ran at 20% all month and hit 60% yesterday
is.

Query-time only, mirroring the Opportunity Finder decision in §17.5: no
persisted anomaly table, no background job, nothing to keep in sync. The cost
is recomputation on each page load, which for this data volume is milliseconds.

Two guards keep the panel worth reading:

  - A minimum spend floor. A campaign going from $0.02 to $0.09 is +350% and
    means nothing. Percentages on tiny numbers are the classic way an anomaly
    panel becomes noise people learn to ignore.
  - A minimum baseline of days with data. Comparing against one quiet Sunday
    manufactures anomalies every Monday.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Below this, percentage change is arithmetic noise rather than signal.
MIN_SPEND_FOR_ANOMALY = 1.00
# Fewer baseline days than this and the comparison is not worth making.
MIN_BASELINE_DAYS = 5

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"


def _pct_change(recent: float, baseline: float) -> Optional[float]:
    if baseline <= 0:
        return None
    return (recent - baseline) / baseline * 100.0


class AnomalyDetector:
    """Compares a recent window against the period before it."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def detect(
        self,
        profile_ids: list[str],
        recent_days: int = 3,
        baseline_days: int = 14,
        spend_change_pct: float = 100.0,
        acos_change_pct: float = 50.0,
    ) -> list[dict[str, Any]]:
        """Return anomalies, most severe first.

        recent_days is short on purpose: the point is "what changed lately",
        and a 14-day recent window would dilute a spike into invisibility.
        """
        if not profile_ids:
            return []

        # Amazon revises attributed sales for days after the click, so the most
        # recent day or two is always incomplete. Ending the recent window
        # yesterday avoids reporting "sales collapsed" every single morning.
        recent_end = date.today() - timedelta(days=1)
        recent_start = recent_end - timedelta(days=recent_days - 1)
        baseline_end = recent_start - timedelta(days=1)
        baseline_start = baseline_end - timedelta(days=baseline_days - 1)

        rows = self.db.execute(sql_text("""
            WITH windows AS (
                SELECT
                    c.id::text            AS campaign_id,
                    c.name                AS campaign_name,
                    c.status              AS campaign_status,
                    c.daily_budget        AS daily_budget,
                    p.country_code        AS marketplace,
                    SUM(CASE WHEN d.date BETWEEN :r_start AND :r_end
                             THEN d.spend ELSE 0 END)                  AS recent_spend,
                    SUM(CASE WHEN d.date BETWEEN :r_start AND :r_end
                             THEN d.sales ELSE 0 END)                  AS recent_sales,
                    SUM(CASE WHEN d.date BETWEEN :r_start AND :r_end
                             THEN d.clicks ELSE 0 END)                 AS recent_clicks,
                    COUNT(DISTINCT CASE WHEN d.date BETWEEN :r_start AND :r_end
                             THEN d.date END)                          AS recent_days,
                    SUM(CASE WHEN d.date BETWEEN :b_start AND :b_end
                             THEN d.spend ELSE 0 END)                  AS base_spend,
                    SUM(CASE WHEN d.date BETWEEN :b_start AND :b_end
                             THEN d.sales ELSE 0 END)                  AS base_sales,
                    COUNT(DISTINCT CASE WHEN d.date BETWEEN :b_start AND :b_end
                             THEN d.date END)                          AS base_days
                FROM campaigns c
                JOIN ads_profiles p ON p.id = c.profile_id
                JOIN campaign_performance_daily d ON d.campaign_id = c.id
                WHERE c.profile_id::text = ANY(:profile_ids)
                  AND c.deleted_at IS NULL
                  AND d.date BETWEEN :b_start AND :r_end
                GROUP BY c.id, c.name, c.status, c.daily_budget, p.country_code
            )
            SELECT * FROM windows
            WHERE base_days >= :min_base_days
        """), {
            "profile_ids": profile_ids,
            "r_start": recent_start, "r_end": recent_end,
            "b_start": baseline_start, "b_end": baseline_end,
            "min_base_days": MIN_BASELINE_DAYS,
        }).mappings().all()

        anomalies: list[dict[str, Any]] = []

        for r in rows:
            recent_days_seen = int(r["recent_days"] or 0)
            if recent_days_seen == 0:
                continue

            recent_spend = float(r["recent_spend"] or 0)
            base_spend = float(r["base_spend"] or 0)
            recent_sales = float(r["recent_sales"] or 0)
            base_sales = float(r["base_sales"] or 0)

            # Compare daily averages, not totals: the windows are different
            # lengths, so raw totals would report a spike that is only the
            # baseline being longer.
            recent_daily = recent_spend / recent_days_seen
            base_daily = base_spend / int(r["base_days"])

            if max(recent_daily, base_daily) < MIN_SPEND_FOR_ANOMALY:
                continue

            base = {
                "campaign_id": r["campaign_id"],
                "campaign_name": r["campaign_name"],
                "marketplace": r["marketplace"],
                "campaign_status": r["campaign_status"],
                "window": {
                    "recent": f"{recent_start} to {recent_end}",
                    "baseline": f"{baseline_start} to {baseline_end}",
                },
            }

            # ── Spend moved sharply ────────────────────────────────────────
            spend_delta = _pct_change(recent_daily, base_daily)
            if spend_delta is not None and abs(spend_delta) >= spend_change_pct:
                direction = "up" if spend_delta > 0 else "down"
                anomalies.append({
                    **base,
                    "type": "spend_change",
                    "severity": SEVERITY_HIGH if abs(spend_delta) >= 200 else SEVERITY_MEDIUM,
                    "headline": (
                        f"Spend {direction} {abs(spend_delta):.0f}% "
                        f"(${base_daily:.2f} → ${recent_daily:.2f} per day)"
                    ),
                    "detail": (
                        "Sudden spend changes usually mean a bid change, a "
                        "competitor's budget running out, or seasonality."
                        if direction == "up" else
                        "Spend dropping without a change from you often means "
                        "the budget is capping out earlier, or bids have fallen "
                        "below the auction floor."
                    ),
                    "metric_delta_pct": round(spend_delta, 1),
                })

            # ── Efficiency moved sharply ───────────────────────────────────
            recent_acos = (recent_spend / recent_sales * 100) if recent_sales else None
            base_acos = (base_spend / base_sales * 100) if base_sales else None

            if recent_acos is not None and base_acos is not None:
                acos_delta = _pct_change(recent_acos, base_acos)
                if acos_delta is not None and acos_delta >= acos_change_pct:
                    anomalies.append({
                        **base,
                        "type": "acos_worsened",
                        "severity": SEVERITY_HIGH if acos_delta >= 100 else SEVERITY_MEDIUM,
                        "headline": (
                            f"ACOS worsened {acos_delta:.0f}% "
                            f"({base_acos:.0f}% → {recent_acos:.0f}%)"
                        ),
                        "detail": "Spending the same money for less return than before.",
                        "metric_delta_pct": round(acos_delta, 1),
                    })
            elif base_sales > 0 and recent_sales == 0 and recent_spend >= MIN_SPEND_FOR_ANOMALY:
                # Worth its own case: a percentage cannot express "went to zero",
                # and this is the most urgent thing the panel can say.
                anomalies.append({
                    **base,
                    "type": "sales_stopped",
                    "severity": SEVERITY_HIGH,
                    "headline": (
                        f"Sales stopped — ${recent_spend:.2f} spent with no orders"
                    ),
                    "detail": (
                        "This campaign was selling during the baseline period and "
                        "is not now. Check the listing is in stock and buyable."
                    ),
                    "metric_delta_pct": None,
                })

            # ── Budget capping out ─────────────────────────────────────────
            # The spec's example is "budget exhausted by 11am, 3 days running".
            # Amazon does not tell us the hour, so the honest signal is spend
            # sitting at the budget ceiling every day.
            budget = float(r["daily_budget"]) if r["daily_budget"] is not None else None
            if (budget and budget > 0 and recent_days_seen >= 2
                    and recent_daily >= budget * 0.95):
                anomalies.append({
                    **base,
                    "type": "budget_capped",
                    "severity": SEVERITY_MEDIUM,
                    "headline": (
                        f"Hitting its daily budget (${recent_daily:.2f} of "
                        f"${budget:.2f} per day)"
                    ),
                    "detail": (
                        "The campaign is spending its whole budget, so it is "
                        "likely stopping early each day and missing later traffic."
                    ),
                    "metric_delta_pct": None,
                })

        severity_rank = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 1}
        anomalies.sort(key=lambda a: (
            severity_rank.get(a["severity"], 9),
            -abs(a["metric_delta_pct"] or 0),
        ))
        logger.info("[anomalies] %d found across %d campaigns",
                    len(anomalies), len(rows))
        return anomalies
