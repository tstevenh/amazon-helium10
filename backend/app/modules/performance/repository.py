"""Database access for performance tables (Sprint 4B)."""
import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class PerformanceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Campaign performance ───────────────────────────────────────────────

    def upsert_campaign_perf(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        stmt = text("""
            INSERT INTO campaign_performance_daily
                (campaign_id, date, impressions, clicks, spend, sales, orders, ctr, cpc, acos, roas)
            VALUES
                (:campaign_id, :date, :impressions, :clicks, :spend, :sales, :orders, :ctr, :cpc, :acos, :roas)
            ON CONFLICT (campaign_id, date) DO UPDATE SET
                impressions = EXCLUDED.impressions,
                clicks      = EXCLUDED.clicks,
                spend       = EXCLUDED.spend,
                sales       = EXCLUDED.sales,
                orders      = EXCLUDED.orders,
                ctr         = EXCLUDED.ctr,
                cpc         = EXCLUDED.cpc,
                acos        = EXCLUDED.acos,
                roas        = EXCLUDED.roas
        """)
        self.db.execute(stmt, rows)
        self.db.commit()
        return len(rows)

    def get_campaign_summary(
        self,
        campaign_id: str,
        date_from: date,
        date_to: date,
    ) -> Optional[dict]:
        stmt = text("""
            SELECT
                SUM(impressions) AS impressions,
                SUM(clicks)      AS clicks,
                SUM(spend)       AS spend,
                SUM(sales)       AS sales,
                SUM(orders)      AS orders
            FROM campaign_performance_daily
            WHERE campaign_id = :campaign_id
              AND date BETWEEN :date_from AND :date_to
        """)
        row = self.db.execute(stmt, {"campaign_id": campaign_id,
                                     "date_from": date_from, "date_to": date_to}).mappings().one_or_none()
        if not row or row["impressions"] is None:
            return None
        impr = int(row["impressions"] or 0)
        clicks = int(row["clicks"] or 0)
        spend = Decimal(str(row["spend"] or 0))
        sales = Decimal(str(row["sales"] or 0))
        orders = int(row["orders"] or 0)
        return {
            "impressions": impr, "clicks": clicks, "spend": spend,
            "sales": sales, "orders": orders,
            "ctr": round(Decimal(clicks) / Decimal(impr), 6) if impr else None,
            "cpc": round(spend / Decimal(clicks), 4) if clicks else None,
            "acos": round(spend / sales * 100, 4) if sales else None,
            "roas": round(sales / spend, 4) if spend else None,
        }

    def get_all_campaigns_summary(
        self,
        campaign_ids: list[str],
        date_from: date,
        date_to: date,
    ) -> dict[str, dict]:
        if not campaign_ids:
            return {}
        stmt = text("""
            SELECT
                campaign_id::text,
                SUM(impressions) AS impressions,
                SUM(clicks)      AS clicks,
                SUM(spend)       AS spend,
                SUM(sales)       AS sales,
                SUM(orders)      AS orders
            FROM campaign_performance_daily
            WHERE campaign_id::text = ANY(:ids)
              AND date BETWEEN :date_from AND :date_to
            GROUP BY campaign_id
        """)
        rows = self.db.execute(stmt, {
            "ids": campaign_ids, "date_from": date_from, "date_to": date_to,
        }).mappings().all()
        result = {}
        for row in rows:
            impr = int(row["impressions"] or 0)
            clicks = int(row["clicks"] or 0)
            spend = Decimal(str(row["spend"] or 0))
            sales = Decimal(str(row["sales"] or 0))
            orders = int(row["orders"] or 0)
            result[row["campaign_id"]] = {
                "impressions": impr, "clicks": clicks, "spend": spend,
                "sales": sales, "orders": orders,
                "ctr": round(Decimal(clicks) / Decimal(impr), 6) if impr else None,
                "cpc": round(spend / Decimal(clicks), 4) if clicks else None,
                "acos": round(spend / sales * 100, 4) if sales else None,
                "roas": round(sales / spend, 4) if spend else None,
            }
        return result

    # ── Ad group performance ───────────────────────────────────────────────

    def upsert_ad_group_perf(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        stmt = text("""
            INSERT INTO ad_group_performance_daily
                (ad_group_id, date, impressions, clicks, spend, sales, orders, ctr, cpc, acos, roas)
            VALUES
                (:ad_group_id, :date, :impressions, :clicks, :spend, :sales, :orders, :ctr, :cpc, :acos, :roas)
            ON CONFLICT (ad_group_id, date) DO UPDATE SET
                impressions = EXCLUDED.impressions,
                clicks      = EXCLUDED.clicks,
                spend       = EXCLUDED.spend,
                sales       = EXCLUDED.sales,
                orders      = EXCLUDED.orders,
                ctr         = EXCLUDED.ctr,
                cpc         = EXCLUDED.cpc,
                acos        = EXCLUDED.acos,
                roas        = EXCLUDED.roas,
                updated_at  = now()
        """)
        self.db.execute(stmt, rows)
        self.db.commit()
        return len(rows)

    def get_ad_group_summary(
        self,
        ad_group_id: str,
        date_from: date,
        date_to: date,
    ) -> Optional[dict]:
        stmt = text("""
            SELECT
                SUM(impressions) AS impressions,
                SUM(clicks)      AS clicks,
                SUM(spend)       AS spend,
                SUM(sales)       AS sales,
                SUM(orders)      AS orders
            FROM ad_group_performance_daily
            WHERE ad_group_id = :ad_group_id
              AND date BETWEEN :date_from AND :date_to
        """)
        row = self.db.execute(stmt, {"ad_group_id": ad_group_id,
                                     "date_from": date_from, "date_to": date_to}).mappings().one_or_none()
        if not row or row["impressions"] is None:
            return None
        impr = int(row["impressions"] or 0)
        clicks = int(row["clicks"] or 0)
        spend = Decimal(str(row["spend"] or 0))
        sales = Decimal(str(row["sales"] or 0))
        orders = int(row["orders"] or 0)
        return {
            "impressions": impr, "clicks": clicks, "spend": spend,
            "sales": sales, "orders": orders,
            "ctr": round(Decimal(clicks) / Decimal(impr), 6) if impr else None,
            "cpc": round(spend / Decimal(clicks), 4) if clicks else None,
            "acos": round(spend / sales * 100, 4) if sales else None,
            "roas": round(sales / spend, 4) if spend else None,
        }

    def get_all_ad_groups_summary(
        self,
        ad_group_ids: list[str],
        date_from: date,
        date_to: date,
    ) -> dict[str, dict]:
        """Return {ad_group_id_str: summary_dict} for a list of ad groups."""
        if not ad_group_ids:
            return {}
        stmt = text("""
            SELECT
                ad_group_id::text,
                SUM(impressions) AS impressions,
                SUM(clicks)      AS clicks,
                SUM(spend)       AS spend,
                SUM(sales)       AS sales,
                SUM(orders)      AS orders
            FROM ad_group_performance_daily
            WHERE ad_group_id::text = ANY(:ids)
              AND date BETWEEN :date_from AND :date_to
            GROUP BY ad_group_id
        """)
        rows = self.db.execute(stmt, {
            "ids": ad_group_ids, "date_from": date_from, "date_to": date_to,
        }).mappings().all()
        result = {}
        for row in rows:
            impr = int(row["impressions"] or 0)
            clicks = int(row["clicks"] or 0)
            spend = Decimal(str(row["spend"] or 0))
            sales = Decimal(str(row["sales"] or 0))
            orders = int(row["orders"] or 0)
            result[row["ad_group_id"]] = {
                "impressions": impr, "clicks": clicks, "spend": spend,
                "sales": sales, "orders": orders,
                "ctr": round(Decimal(clicks) / Decimal(impr), 6) if impr else None,
                "cpc": round(spend / Decimal(clicks), 4) if clicks else None,
                "acos": round(spend / sales * 100, 4) if sales else None,
                "roas": round(sales / spend, 4) if spend else None,
            }
        return result

    # ── Target performance ─────────────────────────────────────────────────

    def upsert_target_perf(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        stmt = text("""
            INSERT INTO target_performance_daily
                (target_id, date, impressions, clicks, spend, sales, orders, ctr, cpc, acos, roas)
            VALUES
                (:target_id, :date, :impressions, :clicks, :spend, :sales, :orders, :ctr, :cpc, :acos, :roas)
            ON CONFLICT (target_id, date) DO UPDATE SET
                impressions = EXCLUDED.impressions,
                clicks      = EXCLUDED.clicks,
                spend       = EXCLUDED.spend,
                sales       = EXCLUDED.sales,
                orders      = EXCLUDED.orders,
                ctr         = EXCLUDED.ctr,
                cpc         = EXCLUDED.cpc,
                acos        = EXCLUDED.acos,
                roas        = EXCLUDED.roas
        """)
        self.db.execute(stmt, rows)
        self.db.commit()
        return len(rows)

    def get_all_targets_summary(
        self,
        target_ids: list[str],
        date_from: date,
        date_to: date,
    ) -> dict[str, dict]:
        """Return {target_id_str: summary_dict} for a list of targets."""
        if not target_ids:
            return {}
        stmt = text("""
            SELECT
                target_id::text,
                SUM(impressions) AS impressions,
                SUM(clicks)      AS clicks,
                SUM(spend)       AS spend,
                SUM(sales)       AS sales,
                SUM(orders)      AS orders
            FROM target_performance_daily
            WHERE target_id::text = ANY(:ids)
              AND date BETWEEN :date_from AND :date_to
            GROUP BY target_id
        """)
        rows = self.db.execute(stmt, {
            "ids": target_ids, "date_from": date_from, "date_to": date_to,
        }).mappings().all()
        result = {}
        for row in rows:
            impr = int(row["impressions"] or 0)
            clicks = int(row["clicks"] or 0)
            spend = Decimal(str(row["spend"] or 0))
            sales = Decimal(str(row["sales"] or 0))
            orders = int(row["orders"] or 0)
            result[row["target_id"]] = {
                "impressions": impr, "clicks": clicks, "spend": spend,
                "sales": sales, "orders": orders,
                "ctr": round(Decimal(clicks) / Decimal(impr), 6) if impr else None,
                "cpc": round(spend / Decimal(clicks), 4) if clicks else None,
                "acos": round(spend / sales * 100, 4) if sales else None,
                "roas": round(sales / spend, 4) if spend else None,
            }
        return result

    # ── Profile-wide "top spenders" listings ───────────────────────────────
    #
    # The Keywords page can only render a few thousand of the account's
    # 231,799 keywords. Slicing them in the API (LIMIT with no ORDER BY)
    # returned an arbitrary 2,000 — mostly zero-traffic keywords — which is
    # why the page looked empty to the team. Rank by spend in SQL instead so
    # a capped list is the capped list that matters.

    _METRIC_SELECT = """
        COALESCE(SUM(p.impressions), 0) AS impressions,
        COALESCE(SUM(p.clicks), 0)      AS clicks,
        COALESCE(SUM(p.spend), 0)       AS spend,
        COALESCE(SUM(p.sales), 0)       AS sales,
        COALESCE(SUM(p.orders), 0)      AS orders
    """

    @staticmethod
    def _derive(row: dict) -> dict:
        """Attach ctr/cpc/acos/roas, leaving them None when undefined.

        None (not 0) matters: a keyword with no clicks has no CPC, and
        showing $0.00 would read as "free clicks".
        """
        impr   = int(row["impressions"] or 0)
        clicks = int(row["clicks"] or 0)
        spend  = Decimal(str(row["spend"] or 0))
        sales  = Decimal(str(row["sales"] or 0))
        return {
            "impressions": impr,
            "clicks": clicks,
            "spend": float(spend),
            "sales": float(sales),
            "orders": int(row["orders"] or 0),
            "ctr":  float(round(Decimal(clicks) / Decimal(impr), 6)) if impr else None,
            "cpc":  float(round(spend / Decimal(clicks), 4)) if clicks else None,
            "acos": float(round(spend / sales * 100, 4)) if sales else None,
            "roas": float(round(sales / spend, 4)) if spend else None,
        }

    def top_ad_groups_by_spend(
        self,
        profile_ids: list[str],
        date_from: date,
        date_to: date,
        limit: int = 2000,
    ) -> list[dict]:
        """Ad groups in the given profiles, highest spend first."""
        if not profile_ids:
            return []
        stmt = text(f"""
            SELECT
                ag.id::text          AS id,
                ag.campaign_id::text AS campaign_id,
                ag.name              AS name,
                ag.status            AS status,
                ag.default_bid       AS default_bid,
                c.profile_id::text   AS profile_id,
                {self._METRIC_SELECT}
            FROM ad_groups ag
            JOIN campaigns c ON c.id = ag.campaign_id
            LEFT JOIN ad_group_performance_daily p
                   ON p.ad_group_id = ag.id
                  AND p.date BETWEEN :date_from AND :date_to
            WHERE c.profile_id::text = ANY(:profile_ids)
              AND ag.deleted_at IS NULL
              AND c.deleted_at IS NULL
            GROUP BY ag.id, ag.campaign_id, ag.name, ag.status, ag.default_bid, c.profile_id
            ORDER BY COALESCE(SUM(p.spend), 0) DESC, ag.name ASC
            LIMIT :limit
        """)
        rows = self.db.execute(stmt, {
            "profile_ids": profile_ids, "date_from": date_from,
            "date_to": date_to, "limit": limit,
        }).mappings().all()
        return [{
            "id": r["id"],
            "campaign_id": r["campaign_id"],
            "profile_id": r["profile_id"],
            "name": r["name"],
            "status": r["status"],
            "default_bid": float(r["default_bid"]) if r["default_bid"] is not None else None,
            **self._derive(r),
        } for r in rows]

    def top_targets_by_spend(
        self,
        profile_ids: list[str],
        date_from: date,
        date_to: date,
        target_kind: Optional[str] = None,
        limit: int = 2000,
    ) -> list[dict]:
        """Targets in the given profiles, highest spend first."""
        if not profile_ids:
            return []
        stmt = text(f"""
            SELECT
                t.id::text            AS id,
                t.ad_group_id::text   AS ad_group_id,
                ag.campaign_id::text  AS campaign_id,
                c.profile_id::text    AS profile_id,
                t.amazon_target_id    AS amazon_target_id,
                t.target_kind         AS target_kind,
                t.match_type          AS match_type,
                t.expression_text     AS expression_text,
                t.bid                 AS bid,
                t.status              AS status,
                {self._METRIC_SELECT}
            FROM targets t
            JOIN ad_groups ag ON ag.id = t.ad_group_id
            JOIN campaigns c  ON c.id  = ag.campaign_id
            LEFT JOIN target_performance_daily p
                   ON p.target_id = t.id
                  AND p.date BETWEEN :date_from AND :date_to
            WHERE c.profile_id::text = ANY(:profile_ids)
              AND (:target_kind IS NULL OR t.target_kind = :target_kind)
              AND t.deleted_at IS NULL
              AND ag.deleted_at IS NULL
              AND c.deleted_at IS NULL
            GROUP BY t.id, t.ad_group_id, ag.campaign_id, c.profile_id,
                     t.amazon_target_id, t.target_kind, t.match_type,
                     t.expression_text, t.bid, t.status
            ORDER BY COALESCE(SUM(p.spend), 0) DESC, t.expression_text ASC
            LIMIT :limit
        """)
        rows = self.db.execute(stmt, {
            "profile_ids": profile_ids, "date_from": date_from, "date_to": date_to,
            "target_kind": target_kind, "limit": limit,
        }).mappings().all()
        return [{
            "id": r["id"],
            "ad_group_id": r["ad_group_id"],
            "campaign_id": r["campaign_id"],
            "profile_id": r["profile_id"],
            # BigInteger — JSON-safe as a string, matching the rest of the API
            "amazon_target_id": str(r["amazon_target_id"]),
            "target_kind": r["target_kind"],
            "match_type": r["match_type"],
            "expression_text": r["expression_text"],
            "bid": float(r["bid"]) if r["bid"] is not None else None,
            "status": r["status"],
            **self._derive(r),
        } for r in rows]

    def count_targets(self, profile_ids: list[str], target_kind: Optional[str] = None) -> int:
        """Total matching targets, so the UI can say '2,000 of 231,799'."""
        if not profile_ids:
            return 0
        stmt = text("""
            SELECT COUNT(*) AS n
            FROM targets t
            JOIN ad_groups ag ON ag.id = t.ad_group_id
            JOIN campaigns c  ON c.id  = ag.campaign_id
            WHERE c.profile_id::text = ANY(:profile_ids)
              AND (:target_kind IS NULL OR t.target_kind = :target_kind)
              AND t.deleted_at IS NULL
              AND ag.deleted_at IS NULL
              AND c.deleted_at IS NULL
        """)
        return int(self.db.execute(stmt, {
            "profile_ids": profile_ids, "target_kind": target_kind,
        }).scalar() or 0)
