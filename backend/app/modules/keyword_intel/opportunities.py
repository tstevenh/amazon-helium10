"""Opportunity Finder and Competitor Comparison (spec §17.5, Phase 3).

All five patterns are QUERY-TIME views, per the spec's explicit decision: "not
a persisted table recalculated by a background job. No new scheduled
infrastructure."

GATED ON DATA, NOT EFFORT
------------------------
§17.6 is blunt: "don't build Opportunity Finder until there are ≥3 real
snapshots per ASIN — trend-based opportunities are meaningless on a single
snapshot." The code is built, and it refuses to pretend: each trend-based
pattern reports how many snapshots it had, and returns nothing rather than
inventing a trend from two points.

The two non-trend patterns (missing from PPC, missing from listings) work from
a single snapshot, so they are useful immediately.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Below this, "search volume" is too small for the opportunity to be worth a
# person's time regardless of how good the trend looks.
MIN_MEANINGFUL_VOLUME = 100

# Trend patterns need this many snapshots for the comparison to mean anything.
MIN_SNAPSHOTS_FOR_TREND = 3


class OpportunityFinder:
    def __init__(self, db: Session) -> None:
        self.db = db

    def snapshot_counts_by_asin(self) -> dict[str, int]:
        """How many completed snapshots cover each ASIN.

        Surfaced so the UI can say "needs 3, has 1" instead of showing an empty
        list that looks like a bug.
        """
        rows = self.db.execute(sql_text("""
            SELECT a.asin, COUNT(DISTINCT s.id) AS n
            FROM ki_snapshot_asins a
            JOIN ki_snapshots s ON s.id = a.snapshot_id AND s.status = 'completed'
            GROUP BY a.asin
            ORDER BY a.asin
        """)).mappings().all()
        return {r["asin"]: int(r["n"]) for r in rows}

    # ── Pattern 1: search volume increasing ────────────────────────────────

    def volume_increasing(self, asin: Optional[str] = None,
                          min_trend_pct: float = 20.0,
                          limit: int = 50) -> list[dict[str, Any]]:
        """Keywords whose search volume is climbing across snapshots.

        Uses first-vs-latest measured volume rather than the source's own
        trend column, because that column describes Amazon's window, not the
        window between your snapshots.
        """
        rows = self.db.execute(sql_text("""
            WITH ranked AS (
                SELECT m.keyword_id, m.asin, m.search_volume, s.snapshot_date,
                       ROW_NUMBER() OVER (PARTITION BY m.keyword_id, m.asin
                                          ORDER BY s.snapshot_date ASC)  AS first_rn,
                       ROW_NUMBER() OVER (PARTITION BY m.keyword_id, m.asin
                                          ORDER BY s.snapshot_date DESC) AS last_rn,
                       COUNT(*) OVER (PARTITION BY m.keyword_id, m.asin)  AS snapshots
                FROM ki_keyword_metrics m
                JOIN ki_snapshots s ON s.id = m.snapshot_id
                WHERE s.status = 'completed'
                  AND m.search_volume IS NOT NULL
                  AND (:asin IS NULL OR m.asin = :asin)
            )
            SELECT k.id::text AS keyword_id, k.keyword_text, f.asin,
                   f.search_volume AS first_volume, l.search_volume AS latest_volume,
                   f.snapshot_date AS first_date, l.snapshot_date AS latest_date,
                   f.snapshots
            FROM ranked f
            JOIN ranked l ON l.keyword_id = f.keyword_id
                         AND COALESCE(l.asin,'') = COALESCE(f.asin,'')
                         AND l.last_rn = 1
            JOIN ki_keywords k ON k.id = f.keyword_id
            WHERE f.first_rn = 1
              AND f.snapshots >= :min_snapshots
              AND l.search_volume >= :min_volume
              AND f.search_volume > 0
              AND (l.search_volume - f.search_volume)::numeric / f.search_volume * 100 >= :min_trend
            ORDER BY (l.search_volume - f.search_volume)::numeric / f.search_volume DESC
            LIMIT :limit
        """), {
            "asin": asin, "min_snapshots": MIN_SNAPSHOTS_FOR_TREND,
            "min_volume": MIN_MEANINGFUL_VOLUME, "min_trend": min_trend_pct,
            "limit": limit,
        }).mappings().all()
        return [{
            **dict(r),
            "change_pct": round(
                (r["latest_volume"] - r["first_volume"]) / r["first_volume"] * 100, 1
            ),
        } for r in rows]

    # ── Pattern 2: organic rank declining ──────────────────────────────────

    def rank_declining(self, asin: Optional[str] = None,
                       min_positions: int = 5,
                       limit: int = 50) -> list[dict[str, Any]]:
        """Keywords where you are slipping organically.

        Rank is inverted: a LARGER number is worse. Filtered to meaningful
        search volume, because slipping on a keyword nobody searches is not an
        opportunity.
        """
        rows = self.db.execute(sql_text("""
            WITH ranked AS (
                SELECT m.keyword_id, m.asin, m.organic_rank, m.search_volume,
                       s.snapshot_date,
                       ROW_NUMBER() OVER (PARTITION BY m.keyword_id, m.asin
                                          ORDER BY s.snapshot_date DESC) AS rn,
                       COUNT(*) OVER (PARTITION BY m.keyword_id, m.asin) AS snapshots
                FROM ki_keyword_metrics m
                JOIN ki_snapshots s ON s.id = m.snapshot_id
                WHERE s.status = 'completed'
                  AND m.organic_rank IS NOT NULL
                  AND (:asin IS NULL OR m.asin = :asin)
            )
            SELECT k.id::text AS keyword_id, k.keyword_text, cur.asin,
                   prev.organic_rank AS previous_rank,
                   cur.organic_rank  AS current_rank,
                   cur.search_volume,
                   prev.snapshot_date AS previous_date,
                   cur.snapshot_date  AS current_date
            FROM ranked cur
            JOIN ranked prev ON prev.keyword_id = cur.keyword_id
                            AND COALESCE(prev.asin,'') = COALESCE(cur.asin,'')
                            AND prev.rn = 2
            JOIN ki_keywords k ON k.id = cur.keyword_id
            WHERE cur.rn = 1
              AND COALESCE(cur.search_volume, 0) >= :min_volume
              AND cur.organic_rank - prev.organic_rank >= :min_positions
            ORDER BY cur.organic_rank - prev.organic_rank DESC
            LIMIT :limit
        """), {
            "asin": asin, "min_volume": MIN_MEANINGFUL_VOLUME,
            "min_positions": min_positions, "limit": limit,
        }).mappings().all()
        return [{**dict(r),
                 "positions_lost": r["current_rank"] - r["previous_rank"]}
                for r in rows]

    # ── Pattern 3: competitor count increasing ─────────────────────────────

    def competition_increasing(self, asin: Optional[str] = None,
                               min_change_pct: float = 15.0,
                               limit: int = 50) -> list[dict[str, Any]]:
        """Keywords getting more crowded — defensive bid-increase candidates."""
        rows = self.db.execute(sql_text("""
            WITH ranked AS (
                SELECT m.keyword_id, m.asin, m.search_volume,
                       COALESCE(m.competing_products_count, 0) AS competitors,
                       COALESCE(m.sponsored_asins_count, 0)    AS sponsored,
                       s.snapshot_date,
                       ROW_NUMBER() OVER (PARTITION BY m.keyword_id, m.asin
                                          ORDER BY s.snapshot_date DESC) AS rn
                FROM ki_keyword_metrics m
                JOIN ki_snapshots s ON s.id = m.snapshot_id
                WHERE s.status = 'completed'
                  AND (:asin IS NULL OR m.asin = :asin)
            )
            SELECT k.id::text AS keyword_id, k.keyword_text, cur.asin,
                   prev.competitors AS previous_competitors,
                   cur.competitors  AS current_competitors,
                   prev.sponsored   AS previous_sponsored,
                   cur.sponsored    AS current_sponsored,
                   cur.search_volume
            FROM ranked cur
            JOIN ranked prev ON prev.keyword_id = cur.keyword_id
                            AND COALESCE(prev.asin,'') = COALESCE(cur.asin,'')
                            AND prev.rn = 2
            JOIN ki_keywords k ON k.id = cur.keyword_id
            WHERE cur.rn = 1
              AND prev.competitors > 0
              AND COALESCE(cur.search_volume, 0) >= :min_volume
              AND (cur.competitors - prev.competitors)::numeric
                  / prev.competitors * 100 >= :min_change
            ORDER BY (cur.competitors - prev.competitors)::numeric / prev.competitors DESC
            LIMIT :limit
        """), {
            "asin": asin, "min_volume": MIN_MEANINGFUL_VOLUME,
            "min_change": min_change_pct, "limit": limit,
        }).mappings().all()
        return [{
            **dict(r),
            "change_pct": round(
                (r["current_competitors"] - r["previous_competitors"])
                / r["previous_competitors"] * 100, 1
            ),
        } for r in rows]

    # ── Pattern 4: keywords missing from PPC ───────────────────────────────

    def missing_from_ppc(self, limit: int = 100) -> list[dict[str, Any]]:
        """Healthy imported keywords you are not bidding on.

        This is the cross-module query the spec calls out (§17.5): Keyword
        Intelligence joined to the core PPC schema. Matching is on normalized
        text against targets.expression_text, since one side comes from a
        Helium 10 export and the other from Amazon.

        Works from a single snapshot, so it is useful before any trend is.
        """
        rows = self.db.execute(sql_text("""
            WITH latest AS (
                SELECT DISTINCT ON (m.keyword_id, m.asin)
                       m.keyword_id, m.asin, m.search_volume,
                       m.competing_products_count, m.cpc
                FROM ki_keyword_metrics m
                JOIN ki_snapshots s ON s.id = m.snapshot_id
                WHERE s.status = 'completed'
                ORDER BY m.keyword_id, m.asin, s.snapshot_date DESC
            )
            SELECT k.id::text AS keyword_id, k.keyword_text, l.asin,
                   l.search_volume, l.competing_products_count, l.cpc
            FROM latest l
            JOIN ki_keywords k ON k.id = l.keyword_id
            WHERE COALESCE(l.search_volume, 0) >= :min_volume
              AND NOT EXISTS (
                  SELECT 1 FROM targets t
                  WHERE t.deleted_at IS NULL
                    AND t.target_kind = 'keyword'
                    AND lower(btrim(t.expression_text)) = k.normalized_text
              )
            ORDER BY l.search_volume DESC
            LIMIT :limit
        """), {"min_volume": MIN_MEANINGFUL_VOLUME, "limit": limit}).mappings().all()
        return [dict(r) for r in rows]

    # ── Pattern 5: keywords missing from listings ──────────────────────────

    def missing_from_listings(self, asin: Optional[str] = None,
                              limit: int = 100) -> list[dict[str, Any]]:
        """Healthy keywords absent from the listing's own copy.

        product_listings is maintained by hand in V1, so every row carries
        last_updated_at — §17.6 asks for that explicitly, so an operator can
        judge for themselves whether the answer is stale.
        """
        rows = self.db.execute(sql_text("""
            WITH latest AS (
                SELECT DISTINCT ON (m.keyword_id, m.asin)
                       m.keyword_id, m.asin, m.search_volume
                FROM ki_keyword_metrics m
                JOIN ki_snapshots s ON s.id = m.snapshot_id
                WHERE s.status = 'completed'
                ORDER BY m.keyword_id, m.asin, s.snapshot_date DESC
            )
            SELECT k.id::text AS keyword_id, k.keyword_text, l.asin,
                   l.search_volume, pl.last_updated_at
            FROM latest l
            JOIN ki_keywords k ON k.id = l.keyword_id
            JOIN product_listings pl ON pl.asin = l.asin
            WHERE COALESCE(l.search_volume, 0) >= :min_volume
              AND (:asin IS NULL OR l.asin = :asin)
              AND position(k.normalized_text in lower(
                    COALESCE(pl.title,'') || ' ' ||
                    COALESCE(array_to_string(pl.bullet_points, ' '), '') || ' ' ||
                    COALESCE(pl.backend_keywords,'')
                  )) = 0
            ORDER BY l.search_volume DESC
            LIMIT :limit
        """), {"asin": asin, "min_volume": MIN_MEANINGFUL_VOLUME,
               "limit": limit}).mappings().all()
        return [dict(r) for r in rows]

    # ── Competitor comparison ──────────────────────────────────────────────

    def compare_asins(self, my_asin: str, competitor_asin: str,
                      limit: int = 200) -> dict[str, Any]:
        """Keyword gap between two ASINs, from the latest snapshot of each.

        A "gap" is a keyword where the competitor ranks and you do not, or
        ranks materially better. Both sides come from imported snapshots, so
        this needs a snapshot covering the competitor's ASIN — which means
        running Cerebro against their ASIN, not yours.
        """
        rows = self.db.execute(sql_text("""
            WITH latest AS (
                SELECT DISTINCT ON (m.keyword_id, m.asin)
                       m.keyword_id, m.asin, m.organic_rank, m.search_volume
                FROM ki_keyword_metrics m
                JOIN ki_snapshots s ON s.id = m.snapshot_id
                WHERE s.status = 'completed' AND m.asin IN (:mine, :theirs)
                ORDER BY m.keyword_id, m.asin, s.snapshot_date DESC
            )
            SELECT k.keyword_text,
                   k.id::text AS keyword_id,
                   mine.organic_rank   AS my_rank,
                   theirs.organic_rank AS competitor_rank,
                   COALESCE(mine.search_volume, theirs.search_volume) AS search_volume
            FROM latest theirs
            LEFT JOIN latest mine ON mine.keyword_id = theirs.keyword_id
                                 AND mine.asin = :mine
            JOIN ki_keywords k ON k.id = theirs.keyword_id
            WHERE theirs.asin = :theirs
              AND theirs.organic_rank IS NOT NULL
              AND COALESCE(theirs.search_volume, 0) >= :min_volume
              AND (mine.organic_rank IS NULL
                   OR mine.organic_rank > theirs.organic_rank)
            ORDER BY COALESCE(theirs.search_volume, 0) DESC
            LIMIT :limit
        """), {"mine": my_asin.upper(), "theirs": competitor_asin.upper(),
               "min_volume": MIN_MEANINGFUL_VOLUME, "limit": limit}).mappings().all()

        gaps = []
        for r in rows:
            gaps.append({
                **dict(r),
                # Distinguishing these matters: one is "they rank and you are
                # invisible", the other is "you both rank and they win".
                "gap_type": "not_ranking" if r["my_rank"] is None else "outranked",
            })
        return {
            "my_asin": my_asin.upper(),
            "competitor_asin": competitor_asin.upper(),
            "gaps": gaps,
            "not_ranking": sum(1 for g in gaps if g["gap_type"] == "not_ranking"),
            "outranked": sum(1 for g in gaps if g["gap_type"] == "outranked"),
        }

    # ── Everything at once, for the screen ─────────────────────────────────

    def all_opportunities(self, asin: Optional[str] = None) -> dict[str, Any]:
        counts = self.snapshot_counts_by_asin()
        enough = (
            max(counts.values(), default=0) >= MIN_SNAPSHOTS_FOR_TREND
            if asin is None else
            counts.get(asin.upper(), 0) >= MIN_SNAPSHOTS_FOR_TREND
        )
        return {
            "snapshot_counts_by_asin": counts,
            "min_snapshots_for_trends": MIN_SNAPSHOTS_FOR_TREND,
            "trends_available": enough,
            # Trend patterns return [] rather than a fabricated trend when
            # there is not enough history. Reported explicitly above so the UI
            # can explain why instead of showing a bare empty list.
            "volume_increasing": self.volume_increasing(asin) if enough else [],
            "rank_declining": self.rank_declining(asin) if enough else [],
            "competition_increasing": self.competition_increasing(asin) if enough else [],
            # These two work from a single snapshot.
            "missing_from_ppc": self.missing_from_ppc(),
            "missing_from_listings": self.missing_from_listings(asin),
        }
