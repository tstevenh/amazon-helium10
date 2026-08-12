"""Built-in rule templates.

These are not invented thresholds. Each one is the shape of a rule that has
already run against a live account in this project, with the numbers that
produced actionable suggestions rather than noise:

  - "Zero-order spend" produced 10 suggestions from 106 search terms
  - "Bid down on high ACOS" produced 4 from 105

A new marketplace starts with no rules at all, and the Rule Builder's blank
condition form offers no hint what a sensible ACoS threshold is. Templates are
the answer to "what should I even put here".

Seeding is idempotent: builtins are matched by name (see the partial unique
index in migration 016), so re-running updates rather than duplicating.
"""
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.modules.rules.models import RuleTemplate

logger = logging.getLogger(__name__)

BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "Zero-order spend → negative exact",
        "description": (
            "Search terms that took clicks or money and produced no orders. "
            "The single highest-value rule in Amazon PPC: it stops known waste "
            "rather than guessing at future performance."
        ),
        "rule_type": "negative",
        "configuration_json": {
            # OR on the thresholds, per spec: either enough clicks or enough
            # spend is sufficient evidence on its own.
            "conditions": [
                {"field": "clicks", "operator": "gte", "value": 10},
                {"field": "cost", "operator": "gte", "value": 5},
            ],
            "logic": "OR",
            "suggestion_type": "negative_exact",
            "lookback_days": 30,
        },
    },
    {
        "name": "High ACOS → lower the bid",
        "description": (
            "Keywords selling, but not profitably. Reduces the bid by 15% "
            "rather than pausing, so the keyword keeps its history and can "
            "recover at a price that works."
        ),
        "rule_type": "bid",
        "configuration_json": {
            "conditions": [
                {"field": "acos", "operator": "gt", "value": 40},
                {"field": "clicks", "operator": "gte", "value": 5},
            ],
            "logic": "AND",
            "suggestion_type": "bid_decrease",
            "lookback_days": 30,
            "action": {"type": "decrease_bid", "percent": 15},
        },
    },
    {
        "name": "Profitable search term → harvest as exact keyword",
        "description": (
            "Terms already converting well inside automatic or broad targeting. "
            "Promoting them to their own exact keyword lets you bid on them "
            "deliberately instead of by accident."
        ),
        "rule_type": "harvest",
        "configuration_json": {
            "conditions": [
                {"field": "orders", "operator": "gte", "value": 2},
                {"field": "acos", "operator": "lte", "value": 30},
            ],
            "logic": "AND",
            "suggestion_type": "keyword_exact",
            "lookback_days": 60,
        },
    },
    {
        "name": "Strong performer → raise the bid",
        "description": (
            "Keywords converting comfortably below your ACoS target — the ones "
            "worth more traffic. Deliberately stricter than the bid-down rule: "
            "spending more should need better evidence than spending less."
        ),
        "rule_type": "bid",
        "configuration_json": {
            "conditions": [
                {"field": "acos", "operator": "lt", "value": 20},
                {"field": "orders", "operator": "gte", "value": 3},
            ],
            "logic": "AND",
            "suggestion_type": "bid_increase",
            "lookback_days": 30,
            "action": {"type": "increase_bid", "percent": 10},
        },
    },
    {
        "name": "Wasted budget → cut the daily spend",
        "description": (
            "Campaigns burning the full daily budget at a poor return. Cuts "
            "20% rather than pausing, so the campaign keeps its history and "
            "its ranking, and you can raise it again once ACoS recovers."
        ),
        "rule_type": "budget",
        "configuration_json": {
            "conditions": [
                {"field": "acos", "operator": "gt", "value": 45},
                {"field": "clicks", "operator": "gte", "value": 20},
            ],
            "logic": "AND",
            "suggestion_type": "budget_decrease",
            "lookback_days": 30,
            "action": {"type": "decrease_budget", "percent": 20},
        },
    },
]


def seed_builtin_templates(db: Session) -> int:
    """Insert or refresh the built-in templates. Returns rows touched."""
    touched = 0
    for spec in BUILTIN_TEMPLATES:
        existing = (
            db.query(RuleTemplate)
            .filter(
                RuleTemplate.name == spec["name"],
                RuleTemplate.is_builtin.is_(True),
                RuleTemplate.deleted_at.is_(None),
            )
            .first()
        )
        if existing is None:
            db.add(RuleTemplate(is_builtin=True, **spec))
        else:
            existing.description = spec["description"]
            existing.rule_type = spec["rule_type"]
            existing.configuration_json = spec["configuration_json"]
        touched += 1
    db.commit()
    logger.info("[templates] seeded %d built-in templates", touched)
    return touched
