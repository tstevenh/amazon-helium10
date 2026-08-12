"""Source-specific parsers, one per source_type (spec §17.4).

CEREBRO COLUMN NAMES — READ THIS BEFORE DEBUGGING AN IMPORT
-----------------------------------------------------------
The alias table below is built from Helium 10's documented Cerebro export
headers, NOT from one of this account's real exports. Helium 10 renames columns
between releases and varies them by plan. So:

  - Unrecognised columns are never dropped. Every original cell is kept in
    `raw_row`, so a mis-mapped header costs you a chart line, not the data.
  - The import reports which columns it recognised and which it ignored, so a
    mismatch is visible immediately instead of surfacing as "the trends screen
    is empty".
  - `ki_column_mappings` is the fix for a mismatch, and needs no code change.

Per-ASIN rank columns: a Cerebro export covering several ASINs has one column
per ASIN whose header IS the ASIN (or contains it), holding that ASIN's organic
rank for the row's keyword. Those are detected by pattern rather than by name,
since the names are different in every file.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any, Iterator, Optional

# B0 followed by 8 alphanumerics is the modern ASIN shape.
_ASIN_RE = re.compile(r"\b(B0[A-Z0-9]{8})\b", re.IGNORECASE)

# our_field -> accepted header spellings, all normalized (lower, collapsed).
# Order matters within a list only for readability; matching is exact-or-contains.
CEREBRO_ALIASES: dict[str, list[str]] = {
    "keyword_text": [
        "keyword phrase", "keyword", "phrase", "search term",
    ],
    "search_volume": [
        "search volume", "sv", "monthly search volume",
    ],
    "search_volume_trend_pct": [
        "search volume trend", "search volume trend %", "sv trend",
    ],
    "organic_rank": [
        "organic rank", "position rank", "position (rank)", "rank",
    ],
    "sponsored_rank": [
        "sponsored rank", "sponsored position",
    ],
    "competing_products_count": [
        "competing products", "competing products count", "products",
    ],
    "sponsored_asins_count": [
        "sponsored asins", "sponsored asins count",
    ],
    "cpc": [
        "suggested ppc bid", "cpc", "suggested bid", "ppc bid",
    ],
    "title_density": [
        "title density",
    ],
    "relevance_score": [
        "relevance score", "cerebro iq score", "competitor performance score",
    ],
    "estimated_sales": [
        "keyword sales", "estimated sales", "sales",
    ],
}

NUMERIC_FIELDS = {
    "search_volume", "organic_rank", "sponsored_rank",
    "competing_products_count", "sponsored_asins_count", "title_density",
    "estimated_sales",
}
DECIMAL_FIELDS = {"search_volume_trend_pct", "cpc", "relevance_score"}


def normalize_header(raw: str) -> str:
    """Lowercase, strip, collapse whitespace, drop surrounding punctuation."""
    h = (raw or "").strip().lower()
    h = re.sub(r"\s+", " ", h)
    return h.strip(" :._-")


def normalize_keyword(raw: str) -> str:
    """The dedup key: lowercase + trim + collapse whitespace (spec §17.3).

    "Sobriety Gifts" and "sobriety  gifts" must resolve to one keyword id, or
    every trend line silently splits in two.
    """
    return re.sub(r"\s+", " ", (raw or "").strip().lower())


def _to_number(value: Any) -> Optional[float]:
    """Coerce an export cell to a number, or None.

    Exports are full of human formatting: "1,234", "$1.23", "45%", ">1000",
    "-", "N/A", "". None means "not stated", which is different from zero — a
    keyword with no organic rank is unranked, not ranked 0.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in {"-", "--", "n/a", "N/A", "NA", "null", "None"}:
        return None
    # Cerebro uses ">1000" or "1000+" for "outside the tracked range".
    s = s.lstrip(">").rstrip("+")
    s = s.replace(",", "").replace("$", "").replace("%", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(value: Any) -> Optional[int]:
    n = _to_number(value)
    return None if n is None else int(round(n))


class ParseResult:
    """Rows plus what the parser understood, so mismatches are visible."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.recognised_columns: dict[str, str] = {}   # our_field -> their header
        self.ignored_columns: list[str] = []
        self.asin_columns: dict[str, str] = {}         # asin -> their header
        self.warnings: list[str] = []


def _match_aliases(headers: list[str], aliases: dict[str, list[str]]) -> dict[str, str]:
    """Map our_field -> the original header that best matches it."""
    normalized = {normalize_header(h): h for h in headers}
    found: dict[str, str] = {}
    for field, options in aliases.items():
        for option in options:
            # Exact match first — "rank" must not steal "organic rank".
            if option in normalized:
                found[field] = normalized[option]
                break
        if field in found:
            continue
        for option in options:
            for norm, original in normalized.items():
                if option in norm and original not in found.values():
                    found[field] = original
                    break
            if field in found:
                break
    return found


def parse_cerebro(content: bytes, mapping: Optional[dict[str, str]] = None) -> ParseResult:
    """Parse a Cerebro CSV export into keyword x ASIN metric rows.

    `mapping` overrides the built-in aliases with a saved ki_column_mappings
    entry ({our_field: their_header}), which is how a header change is fixed
    without touching this file.
    """
    result = ParseResult()

    text = content.decode("utf-8-sig", errors="replace")
    # Sniff the delimiter: Helium 10 exports comma, but European locales and
    # re-saved-from-Excel files use semicolons and would otherwise parse as one
    # giant column.
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)

    headers = [h for h in (reader.fieldnames or []) if h is not None]
    if not headers:
        result.warnings.append("The file has no header row.")
        return result

    found = _match_aliases(headers, CEREBRO_ALIASES)
    if mapping:
        # A saved mapping wins over guessing.
        for field, header in mapping.items():
            if header in headers:
                found[field] = header
    result.recognised_columns = found

    if "keyword_text" not in found:
        result.warnings.append(
            "Could not find a keyword column. Expected a header like "
            "'Keyword Phrase'. Nothing was imported."
        )
        return result

    # Per-ASIN rank columns, detected by pattern because their names vary.
    used_headers = set(found.values())
    for h in headers:
        if h in used_headers:
            continue
        m = _ASIN_RE.search(h)
        if m:
            result.asin_columns[m.group(1).upper()] = h
        else:
            result.ignored_columns.append(h)

    kw_col = found["keyword_text"]

    for raw in reader:
        keyword = (raw.get(kw_col) or "").strip()
        if not keyword:
            continue

        # Every metric key is present on every row, even when the column does
        # not exist in this file. A row whose shape depends on the input file is
        # a trap: the import happens to survive it via .get(), but any consumer
        # indexing directly raises KeyError on some files and not others.
        base: dict[str, Any] = {
            field: None
            for field in (*NUMERIC_FIELDS, *DECIMAL_FIELDS)
        }
        for field, header in found.items():
            if field == "keyword_text":
                continue
            value = raw.get(header)
            if field in NUMERIC_FIELDS:
                base[field] = _to_int(value)
            elif field in DECIMAL_FIELDS:
                base[field] = _to_number(value)

        if result.asin_columns:
            # One output row per ASIN column, each carrying that ASIN's rank.
            for asin, header in result.asin_columns.items():
                row = dict(base)
                row["keyword_text"] = keyword
                row["asin"] = asin
                rank = _to_int(raw.get(header))
                # An ASIN column override is more specific than a generic
                # "Organic Rank" column, so it wins.
                if rank is not None:
                    row["organic_rank"] = rank
                row["raw_row"] = {k: v for k, v in raw.items() if k is not None}
                result.rows.append(row)
        else:
            row = dict(base)
            row["keyword_text"] = keyword
            row["asin"] = None
            row["raw_row"] = {k: v for k, v in raw.items() if k is not None}
            result.rows.append(row)

    if not result.rows:
        result.warnings.append("The file had a header but no usable data rows.")

    return result


def detect_asins(content: bytes, limit_bytes: int = 65536) -> list[str]:
    """ASINs mentioned in the header row, for the confirm step (spec §17.4)."""
    text = content[:limit_bytes].decode("utf-8-sig", errors="replace")
    first_line = text.splitlines()[0] if text.splitlines() else ""
    return sorted({m.upper() for m in _ASIN_RE.findall(first_line)})


PARSERS = {
    # Spec §17.6: "start with Cerebro only — resist building other parsers
    # speculatively". custom_csv goes through the same parser with a saved
    # column mapping supplied, which is the no-code path for other sources.
    "cerebro": parse_cerebro,
    "custom_csv": parse_cerebro,
}
