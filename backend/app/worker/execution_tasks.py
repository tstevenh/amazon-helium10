"""Celery task for executing an approved suggestion.

Separate from sync_account because the failure modes are different: a sync is
long and idempotent, an execution is short and changes a live ad account. Two
consequences:

  - No automatic retry. Celery's default retry-on-failure would re-issue a
    write to Amazon, and a duplicated bid change is worse than a failed one
    that a human can see and re-approve.
  - The task never raises on a business failure. ExecutionService records
    execution_failed and returns a result; raising would let Celery treat it
    as an infrastructure error and retry it.
"""
import logging
import traceback
import uuid

from app.database import SessionLocal
from app.modules.execution.service import ExecutionService
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="execute_suggestion", bind=True, max_retries=0)
def execute_suggestion(self, suggestion_id: str, user_id: str) -> dict:
    """Apply one approved suggestion to Amazon.

    Args:
        suggestion_id: Suggestion UUID as a string (Celery args are JSON).
        user_id:       The user who approved it — recorded as performed_by.
    """
    db = SessionLocal()
    try:
        return ExecutionService(db).execute(
            uuid.UUID(suggestion_id), uuid.UUID(user_id)
        )
    except Exception as exc:
        # Only unexpected errors reach here; business failures are handled
        # inside the service and recorded against the suggestion.
        logger.error("[worker] execute_suggestion crashed for %s: %s\n%s",
                     suggestion_id, exc, traceback.format_exc())
        try:
            db.rollback()
        except Exception:
            pass
        return {"ok": False, "suggestion_id": suggestion_id,
                "status": "error", "detail": f"{type(exc).__name__}: {exc}"}
    finally:
        db.close()
