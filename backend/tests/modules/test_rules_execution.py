"""The rules engine must read search terms, never touch Amazon, and be
ASIN-aware — it creates suggestions through its own path, not the
SuggestionEngine's.
"""
import inspect

from app.modules.rules import service as rules_service
from app.modules.suggestions.asin import asin_safe_suggestion_type, is_asin


def test_execute_reads_search_terms():
    src = inspect.getsource(rules_service.RuleEngine.execute)
    assert "get_aggregated_by_term" in src


def test_execute_records_an_execution_row():
    """A rule run must leave an audit trail even when it matches nothing."""
    src = inspect.getsource(rules_service.RuleEngine.execute)
    assert "exec_repo.create" in src
    assert "complete" in src


def test_rules_never_import_the_amazon_client():
    """Team constraint: 'Rules never apply Amazon changes.'"""
    src = inspect.getsource(rules_service)
    assert "amazon_ads" not in src
    assert "amazon_reporting" not in src


def test_rules_engine_is_asin_aware():
    """Regression: the rules engine has its own _make_suggestion, so the
    SuggestionEngine fix did not cover it. It produced negative_exact rows
    for ASINs, which Amazon will not accept."""
    src = inspect.getsource(rules_service.RuleEngine._make_suggestion)
    assert "asin_safe_suggestion_type" in src


def test_asin_mapping_covers_every_keyword_type():
    """Any keyword-typed suggestion must have a product-target equivalent."""
    asin = "b0fcs8jvp9"
    for kw_type, expected in (
        ("keyword_exact", "product_target"),
        ("keyword_phrase", "product_target"),
        ("keyword_broad", "product_target"),
        ("negative_exact", "negative_product_target"),
        ("negative_phrase", "negative_product_target"),
    ):
        assert asin_safe_suggestion_type(asin, kw_type) == expected


def test_asin_mapping_leaves_text_queries_alone():
    """Applied unconditionally, so it must be a no-op for real queries."""
    for kw_type in ("keyword_exact", "negative_exact", "keyword_broad"):
        assert asin_safe_suggestion_type("boss mug", kw_type) == kw_type


def test_asin_mapping_is_idempotent():
    """Already-mapped types must pass through unchanged."""
    assert asin_safe_suggestion_type("b0fcs8jvp9", "product_target") == "product_target"
    assert asin_safe_suggestion_type(
        "b0fcs8jvp9", "negative_product_target"
    ) == "negative_product_target"


def test_is_asin_handles_empty_and_none_safely():
    assert is_asin("") is False
    assert is_asin(None) is False
