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
