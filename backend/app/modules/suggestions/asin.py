"""ASIN detection for search terms, shared by the suggestion and rules engines.

Search terms that are ASINs come from product-targeting placements, not
customer text queries. Amazon will not accept an ASIN as a keyword — neither
as a positive keyword nor as a negative keyword — so any keyword-typed
suggestion for an ASIN is unactionable noise.

This lives in its own module because two engines create suggestions:
  - suggestions/service.py  (SuggestionEngine._evaluate)
  - rules/service.py        (RuleService._make_suggestion)
Duplicating the pattern in both would let them drift apart, which is exactly
how the bug survived: fixing one left the other producing bad rows.
"""
import re

# Requiring the "0" avoids false positives on real 10-letter queries such as
# "bluebottle" or "blackboard". Terms are lowercased upstream.
#
# Limitation: book ASINs are ISBN-derived and do not start with B0, so those
# are still treated as keyword terms.
_ASIN_RE = re.compile(r"^b0[a-z0-9]{8}$")

# Keyword-typed suggestion types and their product-target equivalents.
_PRODUCT_TARGET_EQUIVALENT = {
    "keyword_exact": "product_target",
    "keyword_phrase": "product_target",
    "keyword_broad": "product_target",
    "negative_exact": "negative_product_target",
    "negative_phrase": "negative_product_target",
}


def is_asin(search_term: str) -> bool:
    """True if the search term is an ASIN placement rather than a text query."""
    return bool(_ASIN_RE.match((search_term or "").lower().strip()))


def asin_safe_suggestion_type(search_term: str, suggestion_type: str) -> str:
    """Map a keyword-typed suggestion to a product target when the term is an ASIN.

    Non-ASIN terms and already-product-target types pass through unchanged, so
    this is safe to apply unconditionally at every suggestion creation site.
    """
    if not is_asin(search_term):
        return suggestion_type
    return _PRODUCT_TARGET_EQUIVALENT.get(suggestion_type, suggestion_type)
