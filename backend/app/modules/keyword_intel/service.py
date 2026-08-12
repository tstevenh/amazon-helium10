"""Snapshot import and trend queries (spec §17.4).

The import is a single transaction per snapshot: either the whole file lands or
none of it does. A half-imported snapshot would poison every trend that crosses
it, and would be invisible — the row count would simply be lower than expected.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date
from typing import Any, Optional

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.modules.keyword_intel.models import (
    KiColumnMapping,
    KiKeyword,
    KiKeywordMetric,
    KiSnapshot,
    KiSnapshotAsin,
)
from app.modules.keyword_intel.parsers import (
    PARSERS,
    detect_asins,
    normalize_keyword,
)

logger = logging.getLogger(__name__)


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class SnapshotImportError(Exception):
    """The file cannot be imported, with a reason a human can act on."""


class KeywordIntelService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Pre-flight ─────────────────────────────────────────────────────────

    def inspect(self, content: bytes, source_type: str,
                mapping_id: Optional[str] = None) -> dict[str, Any]:
        """Parse without saving, so the operator can confirm before committing.

        Spec §17.4 puts a Confirm step between parse and store: the operator
        checks the detected snapshot_date and ASINs. This is what feeds it.
        """
        parser = PARSERS.get(source_type)
        if parser is None:
            raise SnapshotImportError(
                f"No parser for source type '{source_type}'. "
                f"Available: {', '.join(sorted(PARSERS))}."
            )

        mapping = self._load_mapping(mapping_id)
        parsed = parser(content, mapping)
        digest = file_hash(content)

        previous = (
            self.db.query(KiSnapshot)
            .filter(KiSnapshot.file_hash == digest,
                    KiSnapshot.status == "completed")
            .order_by(KiSnapshot.uploaded_at.desc())
            .first()
        )

        return {
            "row_count": len(parsed.rows),
            "detected_asins": sorted(parsed.asin_columns) or detect_asins(content),
            "recognised_columns": parsed.recognised_columns,
            "ignored_columns": parsed.ignored_columns,
            "warnings": parsed.warnings,
            "file_hash": digest,
            # Spec: warn on a duplicate, but allow a re-import if confirmed.
            "duplicate_of": (
                {
                    "id": str(previous.id),
                    "uploaded_at": previous.uploaded_at.isoformat(),
                    "snapshot_date": previous.snapshot_date.isoformat(),
                    "filename": previous.original_filename,
                }
                if previous else None
            ),
        }

    def _load_mapping(self, mapping_id: Optional[str]) -> Optional[dict[str, str]]:
        if not mapping_id:
            return None
        row = (
            self.db.query(KiColumnMapping)
            .filter(KiColumnMapping.id == mapping_id)
            .first()
        )
        return dict(row.mapping_json) if row else None

    # ── Import ─────────────────────────────────────────────────────────────

    def import_snapshot(
        self,
        content: bytes,
        source_type: str,
        snapshot_date: date,
        filename: Optional[str],
        uploaded_by,
        asins: Optional[list[str]] = None,
        mapping_id: Optional[str] = None,
    ) -> KiSnapshot:
        parser = PARSERS.get(source_type)
        if parser is None:
            raise SnapshotImportError(f"No parser for source type '{source_type}'.")

        parsed = parser(content, self._load_mapping(mapping_id))
        if not parsed.rows:
            reason = "; ".join(parsed.warnings) or "no usable rows found"
            raise SnapshotImportError(f"Nothing to import: {reason}")

        snapshot = KiSnapshot(
            source_type=source_type,
            uploaded_by=uploaded_by,
            snapshot_date=snapshot_date,
            original_filename=filename,
            file_hash=file_hash(content),
            row_count=0,
            status="processing",
        )
        self.db.add(snapshot)
        self.db.flush()

        covered = set(a.upper() for a in (asins or []))
        covered.update(parsed.asin_columns)
        covered.update(
            r["asin"].upper() for r in parsed.rows if r.get("asin")
        )
        for asin in sorted(covered):
            self.db.add(KiSnapshotAsin(snapshot_id=snapshot.id, asin=asin))

        try:
            written = self._write_rows(snapshot, parsed.rows)
            snapshot.row_count = written
            snapshot.status = "completed"
            self.db.commit()
        except Exception as exc:
            # All or nothing: a half-imported snapshot would poison every trend
            # that crosses it, and nothing would look wrong.
            self.db.rollback()
            logger.exception("[ki] import failed for %s", filename)
            failed = KiSnapshot(
                source_type=source_type, uploaded_by=uploaded_by,
                snapshot_date=snapshot_date, original_filename=filename,
                file_hash=file_hash(content), row_count=0,
                status="failed", error_message=str(exc)[:2000],
            )
            self.db.add(failed)
            self.db.commit()
            raise SnapshotImportError(f"Import failed and was rolled back: {exc}")

        self.db.refresh(snapshot)
        logger.warning("[ki] imported %d rows from %s (%s)",
                       written, filename, source_type)
        return snapshot

    def _resolve_keyword_ids(self, rows: list[dict]) -> dict[str, Any]:
        """Upsert every distinct keyword once, returning normalized -> id.

        Batched deliberately: a Cerebro export is thousands of rows, and one
        SELECT per row turns a 5-second import into minutes.
        """
        wanted: dict[str, str] = {}
        for r in rows:
            norm = normalize_keyword(r["keyword_text"])
            if norm and norm not in wanted:
                wanted[norm] = r["keyword_text"].strip()

        if not wanted:
            return {}

        existing = {
            k.normalized_text: k.id
            for k in self.db.query(KiKeyword)
            .filter(KiKeyword.normalized_text.in_(list(wanted)))
            .all()
        }

        for norm, original in wanted.items():
            if norm in existing:
                continue
            kw = KiKeyword(keyword_text=original, normalized_text=norm)
            self.db.add(kw)
            self.db.flush()
            existing[norm] = kw.id

        return existing

    def _write_rows(self, snapshot: KiSnapshot, rows: list[dict]) -> int:
        keyword_ids = self._resolve_keyword_ids(rows)

        # One row per (snapshot, keyword, asin) — the unique index enforces it,
        # so a duplicated line in the export must be collapsed here rather than
        # failing the whole import.
        seen: set[tuple] = set()
        written = 0
        for r in rows:
            norm = normalize_keyword(r["keyword_text"])
            kid = keyword_ids.get(norm)
            if kid is None:
                continue
            asin = (r.get("asin") or None)
            key = (kid, asin)
            if key in seen:
                continue
            seen.add(key)

            self.db.add(KiKeywordMetric(
                snapshot_id=snapshot.id,
                keyword_id=kid,
                asin=asin,
                search_volume=r.get("search_volume"),
                search_volume_trend_pct=r.get("search_volume_trend_pct"),
                organic_rank=r.get("organic_rank"),
                sponsored_rank=r.get("sponsored_rank"),
                competing_products_count=r.get("competing_products_count"),
                sponsored_asins_count=r.get("sponsored_asins_count"),
                cpc=r.get("cpc"),
                title_density=r.get("title_density"),
                relevance_score=r.get("relevance_score"),
                estimated_sales=r.get("estimated_sales"),
                raw_row=r.get("raw_row"),
            ))
            written += 1
        return written

    # ── Reads ──────────────────────────────────────────────────────────────

    def list_snapshots(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.execute(sql_text("""
            SELECT s.id::text, s.source_type, s.snapshot_date, s.uploaded_at,
                   s.original_filename, s.row_count, s.status, s.error_message,
                   COALESCE(
                     (SELECT array_agg(a.asin ORDER BY a.asin)
                      FROM ki_snapshot_asins a WHERE a.snapshot_id = s.id),
                     ARRAY[]::varchar[]
                   ) AS asins,
                   u.name AS uploaded_by_name
            FROM ki_snapshots s
            LEFT JOIN users u ON u.id = s.uploaded_by
            ORDER BY s.snapshot_date DESC, s.uploaded_at DESC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()
        return [dict(r) for r in rows]

    def search_keywords(self, q: str, limit: int = 50) -> list[dict[str, Any]]:
        """Keyword search across everything imported, newest metrics first."""
        rows = self.db.execute(sql_text("""
            SELECT k.id::text, k.keyword_text,
                   COUNT(DISTINCT m.snapshot_id) AS snapshot_count,
                   MAX(m.search_volume)           AS latest_search_volume,
                   COUNT(DISTINCT m.asin)         AS asin_count
            FROM ki_keywords k
            JOIN ki_keyword_metrics m ON m.keyword_id = k.id
            WHERE k.normalized_text LIKE :pattern
            GROUP BY k.id, k.keyword_text
            ORDER BY latest_search_volume DESC NULLS LAST
            LIMIT :limit
        """), {"pattern": f"%{normalize_keyword(q)}%", "limit": limit}).mappings().all()
        return [dict(r) for r in rows]

    def keyword_trend(self, keyword_id: str,
                      asin: Optional[str] = None) -> list[dict[str, Any]]:
        """One point per snapshot, oldest first, for the trend chart.

        Ordered by snapshot_date (what the data represents) rather than
        uploaded_at, so a late upload of older data plots where it belongs.
        """
        rows = self.db.execute(sql_text("""
            SELECT s.snapshot_date, s.source_type, m.asin,
                   m.search_volume, m.search_volume_trend_pct,
                   m.organic_rank, m.sponsored_rank,
                   m.competing_products_count, m.sponsored_asins_count,
                   m.cpc, m.title_density, m.estimated_sales
            FROM ki_keyword_metrics m
            JOIN ki_snapshots s ON s.id = m.snapshot_id
            WHERE m.keyword_id = :kid
              AND s.status = 'completed'
              AND (:asin IS NULL OR m.asin = :asin)
            ORDER BY s.snapshot_date ASC
        """), {"kid": keyword_id, "asin": asin}).mappings().all()
        return [dict(r) for r in rows]

    def snapshot_keywords(self, snapshot_id: str, limit: int = 500,
                          search: Optional[str] = None) -> list[dict[str, Any]]:
        rows = self.db.execute(sql_text("""
            SELECT k.id::text AS keyword_id, k.keyword_text, m.asin,
                   m.search_volume, m.organic_rank, m.sponsored_rank,
                   m.competing_products_count, m.cpc, m.title_density
            FROM ki_keyword_metrics m
            JOIN ki_keywords k ON k.id = m.keyword_id
            WHERE m.snapshot_id = :sid
              AND (:search IS NULL OR k.normalized_text LIKE :pattern)
            ORDER BY m.search_volume DESC NULLS LAST
            LIMIT :limit
        """), {
            "sid": snapshot_id, "limit": limit,
            "search": normalize_keyword(search) if search else None,
            "pattern": f"%{normalize_keyword(search)}%" if search else None,
        }).mappings().all()
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        row = self.db.execute(sql_text("""
            SELECT
              (SELECT COUNT(*) FROM ki_snapshots WHERE status='completed') AS snapshots,
              -- Only keywords that still have metrics. ki_keywords is a
              -- master dedup table and deliberately keeps entries after a
              -- snapshot is deleted, so counting it directly reported
              -- "4 keywords tracked" on an account with no data at all.
              (SELECT COUNT(DISTINCT keyword_id) FROM ki_keyword_metrics)   AS keywords,
              (SELECT COUNT(*) FROM ki_keyword_metrics)                    AS metrics,
              (SELECT COUNT(DISTINCT asin) FROM ki_snapshot_asins)         AS asins,
              (SELECT MIN(snapshot_date) FROM ki_snapshots WHERE status='completed') AS first_date,
              (SELECT MAX(snapshot_date) FROM ki_snapshots WHERE status='completed') AS last_date
        """)).mappings().first()
        return dict(row) if row else {}
