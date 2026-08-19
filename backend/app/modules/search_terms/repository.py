"""Repository for search_terms (Sprint 2)."""
from __future__ import annotations
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.search_terms.models import SearchTerm


class SearchTermRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert(self, data: dict) -> SearchTerm:
        """UPSERT a single search term record keyed by (profile_id, ad_group_id, search_term, date)."""
        existing = (
            self.db.query(SearchTerm)
            .filter_by(
                profile_id=data["profile_id"],
                ad_group_id=data.get("ad_group_id"),
                search_term=data["search_term"],
                date=data["date"],
            )
            .first()
        )
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            self.db.flush()
            return existing
        st = SearchTerm(**data)
        self.db.add(st)
        self.db.flush()
        return st

    def get_aggregated(
        self,
        profile_id: uuid.UUID,
        date_from: date,
        date_to: date,
        campaign_id: Optional[uuid.UUID] = None,
        ad_group_id: Optional[uuid.UUID] = None,
        min_spend: Optional[float] = None,
        min_sales: Optional[float] = None,
        max_acos: Optional[float] = None,
        q: Optional[str] = None,
    ) -> list[dict]:
        """Return search terms aggregated per (profile, campaign, ad_group) for the search-terms UI."""
        filters = ["st.profile_id = :profile_id", "st.date >= :date_from", "st.date <= :date_to"]
        params: dict = {
            "profile_id": str(profile_id),
            "date_from": date_from,
            "date_to": date_to,
        }
        if campaign_id:
            filters.append("st.campaign_id = :campaign_id")
            params["campaign_id"] = str(campaign_id)
        # Amazon exposes search terms at ad-group level, and so does this table:
        # rows are already grouped per (search_term, campaign, ad_group). One
        # campaign's ad groups can target completely different keywords and
        # ASINs, so filtering by campaign alone mixes them together.
        if ad_group_id:
            filters.append("st.ad_group_id = :ad_group_id")
            params["ad_group_id"] = str(ad_group_id)
        if q:
            filters.append("st.search_term ILIKE :q")
            params["q"] = f"%{q}%"

        where_clause = " AND ".join(filters)

        having_parts = []
        if min_spend is not None:
            having_parts.append("SUM(st.cost) >= :min_spend")
            params["min_spend"] = min_spend
        if min_sales is not None:
            having_parts.append("SUM(st.sales) >= :min_sales")
            params["min_sales"] = min_sales
        if max_acos is not None:
            having_parts.append(
                "(SUM(st.sales) > 0 AND SUM(st.cost) / SUM(st.sales) <= :max_acos)"
            )
            params["max_acos"] = max_acos

        having_clause = ("HAVING " + " AND ".join(having_parts)) if having_parts else ""

        sql = text(f"""
            SELECT
                st.search_term,
                st.campaign_id,
                c.name  AS campaign_name,
                st.ad_group_id,
                ag.name AS ad_group_name,
                SUM(st.impressions)::INTEGER    AS impressions,
                SUM(st.clicks)::INTEGER         AS clicks,
                SUM(st.cost)                    AS cost,
                SUM(st.sales)                   AS sales,
                SUM(st.orders)::INTEGER         AS orders,
                SUM(st.units)::INTEGER          AS units,
                CASE WHEN SUM(st.impressions) > 0
                     THEN SUM(st.clicks)::NUMERIC / SUM(st.impressions)
                     ELSE 0 END                 AS ctr,
                CASE WHEN SUM(st.clicks) > 0
                     THEN SUM(st.cost) / SUM(st.clicks)
                     ELSE 0 END                 AS cpc,
                CASE WHEN SUM(st.sales) > 0
                     THEN SUM(st.cost) / SUM(st.sales)
                     ELSE NULL END              AS acos,
                CASE WHEN SUM(st.cost) > 0
                     THEN SUM(st.sales) / SUM(st.cost)
                     ELSE NULL END              AS roas,
                CASE WHEN SUM(st.clicks) > 0
                     THEN SUM(st.orders)::NUMERIC / SUM(st.clicks)
                     ELSE 0 END                 AS conversion_rate
            FROM search_terms st
            LEFT JOIN campaigns c  ON c.id  = st.campaign_id
            LEFT JOIN ad_groups ag ON ag.id = st.ad_group_id
            WHERE {where_clause}
            GROUP BY st.search_term, st.campaign_id, c.name, st.ad_group_id, ag.name
            {having_clause}
            ORDER BY SUM(st.cost) DESC
        """)

        rows = self.db.execute(sql, params).mappings().all()
        return [dict(r) for r in rows]

    def get_aggregated_by_term(
        self,
        profile_id: uuid.UUID,
        date_from: date,
        date_to: date,
        campaign_ids: Optional[list[uuid.UUID]] = None,
    ) -> list[dict]:
        """Return search terms aggregated per (profile, search_term) — across all campaigns/ad groups.

        Used by the suggestion engine (Sprint 2.5) to produce deduplicated suggestions.
        Returns campaign_count and ad_group_count in addition to summed metrics.
        campaign_id / ad_group_id represent the primary (first) occurrence for FK storage.
        """
        sql = text("""
            SELECT
                st.search_term,
                COUNT(DISTINCT st.campaign_id)::INTEGER   AS campaign_count,
                COUNT(DISTINCT st.ad_group_id)::INTEGER   AS ad_group_count,
                MIN(st.campaign_id::TEXT)::UUID            AS campaign_id,
                MIN(st.ad_group_id::TEXT)::UUID            AS ad_group_id,
                SUM(st.impressions)::INTEGER              AS impressions,
                SUM(st.clicks)::INTEGER                   AS clicks,
                SUM(st.cost)                              AS cost,
                SUM(st.sales)                             AS sales,
                SUM(st.orders)::INTEGER                   AS orders,
                SUM(st.units)::INTEGER                    AS units,
                CASE WHEN SUM(st.impressions) > 0
                     THEN SUM(st.clicks)::NUMERIC / SUM(st.impressions)
                     ELSE 0 END                           AS ctr,
                CASE WHEN SUM(st.clicks) > 0
                     THEN SUM(st.cost) / SUM(st.clicks)
                     ELSE 0 END                           AS cpc,
                CASE WHEN SUM(st.sales) > 0
                     THEN SUM(st.cost) / SUM(st.sales)
                     ELSE NULL END                        AS acos,
                CASE WHEN SUM(st.cost) > 0
                     THEN SUM(st.sales) / SUM(st.cost)
                     ELSE NULL END                        AS roas,
                CASE WHEN SUM(st.clicks) > 0
                     THEN SUM(st.orders)::NUMERIC / SUM(st.clicks)
                     ELSE 0 END                           AS conversion_rate
            FROM search_terms st
            WHERE st.profile_id = :profile_id
              AND st.date >= :date_from
              AND st.date <= :date_to
              -- NULL campaign_ids means profile-wide, which is how every
              -- rule behaved before scoping existed.
              AND (:campaign_ids IS NULL
                   OR st.campaign_id::TEXT = ANY(:campaign_ids))
            GROUP BY st.search_term
            ORDER BY SUM(st.cost) DESC
        """)

        params = {
            "profile_id": str(profile_id),
            "date_from": date_from,
            "date_to": date_to,
            "campaign_ids": [str(c) for c in campaign_ids] if campaign_ids else None,
        }
        rows = self.db.execute(sql, params).mappings().all()
        return [dict(r) for r in rows]

    def count_by_profile(self, profile_id: uuid.UUID) -> int:
        return self.db.query(SearchTerm).filter_by(profile_id=profile_id).count()
