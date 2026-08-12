"""Parsing exports written by humans and spreadsheets.

Export cells are not clean numbers. Cerebro writes "1,234", "$0.84", "8.5%",
">1000" and "-", and files that have been through Excel come back with
semicolons and a BOM. Each of those is a real observed shape, and each is
tested individually because the failure mode is silent: a cell that fails to
parse becomes NULL, and a NULL just looks like missing data.

The alias table itself is not tested for correctness against Helium 10 — it
cannot be, without one of their real exports. What IS tested is that a
mismatch is loud: unrecognised columns are reported, and nothing is discarded.
"""
import pytest

from app.modules.keyword_intel.parsers import (
    CEREBRO_ALIASES,
    detect_asins,
    normalize_header,
    normalize_keyword,
    parse_cerebro,
    _to_int,
    _to_number,
)

HEADER = ("Keyword Phrase,Search Volume,Search Volume Trend,Competing Products,"
          "Sponsored ASINs,Title Density,Suggested PPC Bid,Keyword Sales,"
          "B0DDWZ329T,B0CJLLWPMY\n")


def csv_bytes(*rows: str) -> bytes:
    return (HEADER + "".join(r + "\n" for r in rows)).encode()


# ── Number coercion ────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("1234", 1234),
    ('"1,234"', 1234),        # thousands separator
    ("1,234", 1234),
    ("$0.84", 0.84),
    ("8.5%", 8.5),
    ("-2.1%", -2.1),
    (">1000", 1000),          # Cerebro: outside the tracked range
    ("1000+", 1000),
    ("  42  ", 42),
])
def test_human_formatted_numbers_are_parsed(raw, expected):
    assert _to_number(raw.strip('"')) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["", "   ", "-", "--", "n/a", "N/A", "null", None])
def test_absent_values_become_none_not_zero(raw):
    """None means "not stated". Zero would be a claim.

    A keyword with no organic rank is unranked, which is very different from
    ranked #0 — and would sort to the top of every "best rank" view.
    """
    assert _to_number(raw) is None
    assert _to_int(raw) is None


def test_unparseable_text_is_none_rather_than_an_exception():
    """One bad cell must not abort an import of 40,000 rows."""
    assert _to_number("about a thousand") is None


# ── Keyword normalization ──────────────────────────────────────────────────

def test_normalization_collapses_case_and_whitespace():
    """These must resolve to ONE keyword id or every trend line splits in two."""
    variants = [
        "sobriety gifts for women",
        "Sobriety Gifts For Women",
        "  sobriety  gifts   for women ",
        "SOBRIETY GIFTS FOR WOMEN",
    ]
    normalized = {normalize_keyword(v) for v in variants}
    assert len(normalized) == 1


def test_header_normalization_is_tolerant_of_punctuation():
    assert normalize_header("  Search Volume  ") == "search volume"
    assert normalize_header("Search Volume:") == "search volume"
    assert normalize_header("SEARCH   VOLUME") == "search volume"


# ── Structure ──────────────────────────────────────────────────────────────

def test_one_row_per_keyword_times_asin():
    """Two ASIN columns and two keywords means four metric rows."""
    result = parse_cerebro(csv_bytes(
        'kw one,"1,000",5%,100,3,1,$0.50,10,7,23',
        'kw two,"2,000",5%,100,3,1,$0.50,10,9,31',
    ))
    assert len(result.rows) == 4
    assert set(result.asin_columns) == {"B0DDWZ329T", "B0CJLLWPMY"}


def test_each_asin_row_carries_that_asins_own_rank():
    result = parse_cerebro(csv_bytes('kw one,"1,000",5%,100,3,1,$0.50,10,7,23'))
    ranks = {r["asin"]: r["organic_rank"] for r in result.rows}
    assert ranks == {"B0DDWZ329T": 7, "B0CJLLWPMY": 23}


def test_blank_rank_for_one_asin_does_not_affect_the_other():
    result = parse_cerebro(csv_bytes('kw one,"1,000",5%,100,3,1,$0.50,10,-,88'))
    ranks = {r["asin"]: r["organic_rank"] for r in result.rows}
    assert ranks["B0DDWZ329T"] is None
    assert ranks["B0CJLLWPMY"] == 88


def test_rows_without_a_keyword_are_skipped():
    """Trailing blank lines and totals rows are common in exports."""
    result = parse_cerebro(csv_bytes(
        'kw one,"1,000",5%,100,3,1,$0.50,10,7,23',
        ',,,,,,,,,',
    ))
    assert len(result.rows) == 2      # one keyword x two ASINs


def test_every_original_column_is_kept_in_raw_row():
    """A mis-mapped header costs a chart line, never the data (spec §17.3)."""
    header = "Keyword Phrase,Search Volume,Some Future Metric\n"
    content = (header + "kw one,1000,42\n").encode()
    result = parse_cerebro(content)
    assert result.rows[0]["raw_row"]["Some Future Metric"] == "42"


def test_unrecognised_columns_are_reported_not_silently_dropped():
    header = "Keyword Phrase,Search Volume,ABA Total Click Share\n"
    result = parse_cerebro((header + "kw one,1000,4.2%\n").encode())
    assert "ABA Total Click Share" in result.ignored_columns


def test_a_missing_keyword_column_fails_loudly_and_imports_nothing():
    """Better an explicit refusal than a snapshot of zero rows."""
    result = parse_cerebro(b"Volume,Rank\n1000,5\n")
    assert result.rows == []
    assert result.warnings
    assert "keyword" in result.warnings[0].lower()


def test_semicolon_delimited_files_are_handled():
    """Excel in a European locale re-saves CSV with semicolons."""
    content = "Keyword Phrase;Search Volume\nkw one;1000\n".encode()
    result = parse_cerebro(content)
    assert len(result.rows) == 1
    assert result.rows[0]["search_volume"] == 1000


def test_utf8_bom_does_not_corrupt_the_first_header():
    """A BOM makes the first column name unmatchable if not stripped."""
    content = "﻿Keyword Phrase,Search Volume\nkw one,1000\n".encode("utf-8")
    result = parse_cerebro(content)
    assert result.rows and result.rows[0]["keyword_text"] == "kw one"


def test_exact_header_match_beats_a_substring_match():
    """"Organic Rank" must not be captured by the bare alias "rank"."""
    header = "Keyword Phrase,Organic Rank,Sponsored Rank\nkw,5,9\n"
    result = parse_cerebro(header.encode())
    assert result.recognised_columns["organic_rank"] == "Organic Rank"
    assert result.recognised_columns["sponsored_rank"] == "Sponsored Rank"


# ── ASIN detection ─────────────────────────────────────────────────────────

def test_asins_are_detected_from_the_header_row():
    assert detect_asins(csv_bytes()) == ["B0CJLLWPMY", "B0DDWZ329T"]


def test_a_file_with_no_asin_columns_still_parses():
    """A single-ASIN Cerebro export has no per-ASIN columns at all."""
    header = "Keyword Phrase,Search Volume,Organic Rank\n"
    result = parse_cerebro((header + "kw one,1000,5\n").encode())
    assert len(result.rows) == 1
    assert result.rows[0]["asin"] is None
    assert result.rows[0]["organic_rank"] == 5


# ── Alias table sanity ─────────────────────────────────────────────────────

def test_the_keyword_alias_is_present_because_nothing_works_without_it():
    assert "keyword_text" in CEREBRO_ALIASES
    assert CEREBRO_ALIASES["keyword_text"]


def test_aliases_are_all_normalized_form():
    """An alias with capitals or double spaces could never match."""
    for field, options in CEREBRO_ALIASES.items():
        for option in options:
            assert option == normalize_header(option), (
                f"alias {option!r} for {field} is not in normalized form"
            )
