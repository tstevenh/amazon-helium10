"""Scheduled rule evaluation.

Spec workflow 4: "Daily job evaluates the rule against synced data →
generates suggestions." Rules were only ever run by clicking a button.

No kill-switch interaction: rules never write to Amazon. Per the spec, "In
V1 'executing' a rule means PRODUCING A SUGGESTION, not writing to Amazon."
A human still has to approve and apply each one.
"""
import logging

from app.database import SessionLocal
from app.modules.auth.models import User
from app.modules.rules.models import Rule
from app.modules.rules.service import RuleEngine
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="evaluate_all_rules")
def evaluate_all_rules() -> dict:
    """Evaluate every enabled rule. One failure must not stop the others."""
    db = SessionLocal()
    try:
        rules = (
            db.query(Rule)
            .filter(Rule.status == "enabled", Rule.deleted_at.is_(None))
            .all()
        )
        # Attribute scheduled runs to the first admin; the spec's audit model
        # wants a who on every suggestion, and 'the scheduler' is not a user.
        actor = db.query(User).filter(User.role == "admin").first()
        actor_id = actor.id if actor else None

        engine = RuleEngine(db)
        evaluated = 0
        suggestions = 0
        failures: list[str] = []

        for rule in rules:
            try:
                result = engine.execute(rule, actor_id)
                evaluated += 1
                suggestions += result.get("suggestions_generated", 0)
            except Exception as exc:
                # Record and continue — one bad rule must not silence the rest.
                msg = f"rule {rule.id} ({rule.name}): {exc}"
                logger.error("[beat] rule evaluation failed — %s", msg)
                failures.append(msg)
                try:
                    db.rollback()
                except Exception:
                    pass

        logger.warning(
            "[beat] rule evaluation: %d/%d rules, %d suggestions, %d failures",
            evaluated, len(rules), suggestions, len(failures),
        )
        return {
            "rules_total": len(rules),
            "rules_evaluated": evaluated,
            "suggestions_generated": suggestions,
            "failures": failures,
        }
    finally:
        db.close()
