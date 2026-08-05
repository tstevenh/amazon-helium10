"""ASIN search terms must become product targets, never keywords.

Verified 2026-08-05 against live data: 7 of 9 generated suggestions
recommended adding an ASIN as an exact-match keyword. Amazon will not
accept that, so most of the module's output was unusable.
"""
import inspect

from app.modules.suggestions import service as sugg_service


def test_asin_pattern_exists():
    assert hasattr(sugg_service, "_ASIN_RE")


def test_asin_pattern_matches_real_asins():
    """Every ASIN observed in the live search-term data."""
    for asin in ("b0fcs8jvp9", "b07gn4jsx1", "b097grrmqy", "b084rlx76q",
                 "b09v4n316j", "b0dt4c83qg", "b0fhwph8fq"):
        assert sugg_service._ASIN_RE.match(asin), f"{asin} should match"


def test_asin_pattern_does_not_match_real_queries():
    """False positives would silently drop legitimate keyword suggestions.

    'bluebottle' is the motivating case: 10 characters starting with 'b',
    which a looser pattern would misclassify.
    """
    for term in ("boss mug", "sobriety gifts for women", "bluebottle",
                 "microbiology mug", "chief engineer cup", "b0", "blackboard"):
        assert not sugg_service._ASIN_RE.match(term), f"{term} must not match"


def test_evaluate_routes_asins_to_product_target():
    src = inspect.getsource(sugg_service.SuggestionEngine._evaluate)
    assert "_ASIN_RE" in src, "_evaluate must branch on ASIN terms"
    assert "product_target" in src


def test_asin_branch_returns_before_keyword_rules():
    """Match types (exact/phrase/broad) are meaningless for a product target,
    so the ASIN branch must not fall through into the keyword rules."""
    src = inspect.getsource(sugg_service.SuggestionEngine._evaluate)
    asin_start = src.index("if is_asin:")
    keyword_start = src.index("keyword_exact")
    assert asin_start < keyword_start, "ASIN branch must precede keyword rules"
    asin_branch = src[asin_start:keyword_start]
    assert "return created" in asin_branch, "ASIN branch must return early"


def test_asin_suggestion_types_fit_the_column():
    """suggestion_type is varchar(50)."""
    for t in ("product_target", "negative_product_target"):
        assert len(t) <= 50
