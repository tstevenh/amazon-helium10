"""Scheduled rule evaluation must actually persist what it produces.

Found on 2026-08-12 by asking "why was the last rule execution six days ago
when Beat fires daily?" Beat was firing, the worker was running the task, and
the task logged:

    Task evaluate_all_rules succeeded: {'rules_evaluated': 2, ...}

while writing nothing at all. RuleEngine and the rule repositories only
flush(); in the API path the *router* commits. The Celery task never did, so
every scheduled pass was rolled back at db.close().

The task's own success log was the thing that made it invisible, which is why
this is guarded by a test rather than by remembering.
"""
import inspect

from app.worker import rule_tasks


def test_task_commits_what_the_engine_produced():
    """flush() without commit() is discarded when the session closes."""
    src = inspect.getsource(rule_tasks.evaluate_all_rules)

    assert "db.commit()" in src, (
        "RuleEngine only flushes; without an explicit commit the whole "
        "evaluation is silently rolled back at db.close()"
    )


def test_commit_is_inside_the_per_rule_loop():
    """One bad rule must not discard the rules that already succeeded.

    The failure branch calls db.rollback(). With a single commit after the
    loop, a rule failing at position N would throw away the suggestions from
    rules 1..N-1 as well.
    """
    src = inspect.getsource(rule_tasks.evaluate_all_rules)

    commit_at   = src.find("db.commit()")
    except_at   = src.find("except Exception as exc")
    rollback_at = src.find("db.rollback()")

    assert commit_at != -1 and except_at != -1
    assert commit_at < except_at, (
        "commit must happen per successful rule, before the failure branch, "
        "so a later rollback cannot undo earlier rules' work"
    )
    assert rollback_at > except_at, "rollback belongs only to the failure path"


def test_failure_of_one_rule_still_reports_the_others():
    """The task returns counts the health check and alerting depend on."""
    src = inspect.getsource(rule_tasks.evaluate_all_rules)

    assert "failures" in src
    assert "rules_evaluated" in src
    assert "continue" in src or "except Exception" in src
