"""Built-in templates must stay executable by the rules engine.

A template's whole job is to produce a rule that runs. If a template's
suggestion_type or field name drifts away from what RuleEngine understands,
the failure surfaces as "I created a rule from your template and it found
nothing" — which reads as a data problem, not a config typo.
"""
import pytest

from app.modules.rules.templates import BUILTIN_TEMPLATES

# Mirrors ck_rule_templates_rule_type in migration 016.
_DB_ALLOWED_RULE_TYPES = {"negative", "harvest", "bid", "budget"}

# What the frontend's FIELD_OPTIONS and RuleEngine._matches actually support.
_KNOWN_FIELDS = {
    "clicks", "orders", "cost", "sales", "acos", "roas", "ctr",
    "conversion_rate", "impressions",
}
_KNOWN_OPERATORS = {"gt", "gte", "lt", "lte", "eq", "neq"}
_KNOWN_SUGGESTION_TYPES = {
    "negative_exact", "negative_phrase",
    "keyword_exact", "keyword_phrase", "keyword_broad",
    "bid_decrease", "bid_increase",
}


def test_there_is_at_least_one_template_per_core_rule_type():
    """A new operator should find a starting point for each rule kind."""
    types = {t["rule_type"] for t in BUILTIN_TEMPLATES}
    assert {"negative", "harvest", "bid"} <= types


@pytest.mark.parametrize("template", BUILTIN_TEMPLATES, ids=lambda t: t["name"])
def test_template_rule_type_survives_the_database_constraint(template):
    assert template["rule_type"] in _DB_ALLOWED_RULE_TYPES


@pytest.mark.parametrize("template", BUILTIN_TEMPLATES, ids=lambda t: t["name"])
def test_template_conditions_use_fields_the_engine_understands(template):
    config = template["configuration_json"]
    conditions = config.get("conditions", [])
    assert conditions, "a template with no conditions matches nothing"

    for cond in conditions:
        assert cond["field"] in _KNOWN_FIELDS, f"unknown field {cond['field']}"
        assert cond["operator"] in _KNOWN_OPERATORS, f"unknown operator {cond['operator']}"
        assert isinstance(cond["value"], (int, float))


@pytest.mark.parametrize("template", BUILTIN_TEMPLATES, ids=lambda t: t["name"])
def test_template_suggestion_type_matches_its_rule_type(template):
    """A harvest rule emitting a negative suggestion would be unactionable."""
    config = template["configuration_json"]
    sugg = config["suggestion_type"]
    assert sugg in _KNOWN_SUGGESTION_TYPES

    prefix = {"negative": "negative_", "harvest": "keyword_", "bid": "bid_"}
    assert sugg.startswith(prefix[template["rule_type"]]), (
        f"{template['rule_type']} rule must not create a {sugg} suggestion"
    )


@pytest.mark.parametrize("template", BUILTIN_TEMPLATES, ids=lambda t: t["name"])
def test_bid_templates_carry_an_action(template):
    """Without an action a bid rule has no percentage to apply."""
    if template["rule_type"] != "bid":
        return
    action = template["configuration_json"].get("action")
    assert action, "bid template needs an action"
    assert action["type"] in {"increase_bid", "decrease_bid"}
    assert 0 < action["percent"] <= 100


@pytest.mark.parametrize("template", BUILTIN_TEMPLATES, ids=lambda t: t["name"])
def test_lookback_is_within_the_range_amazon_retains(template):
    """The app pulls 90 days; a longer lookback would silently see less."""
    assert 1 <= template["configuration_json"]["lookback_days"] <= 90


def test_raising_a_bid_demands_more_evidence_than_lowering_one():
    """Spending more should be harder to trigger than spending less.

    Not a style preference: an over-eager increase costs money immediately,
    while an over-eager decrease only slows a keyword down.
    """
    by_sugg = {
        t["configuration_json"]["suggestion_type"]: t["configuration_json"]
        for t in BUILTIN_TEMPLATES if t["rule_type"] == "bid"
    }
    up, down = by_sugg.get("bid_increase"), by_sugg.get("bid_decrease")
    assert up and down

    up_pct = up["action"]["percent"]
    down_pct = down["action"]["percent"]
    assert up_pct <= down_pct, (
        f"increase step ({up_pct}%) must not exceed the decrease step ({down_pct}%)"
    )


def test_builtin_names_are_unique():
    """Seeding matches builtins by name, so duplicates would fight each other."""
    names = [t["name"] for t in BUILTIN_TEMPLATES]
    assert len(names) == len(set(names))
