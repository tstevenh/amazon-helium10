"""Execution endpoints — approved suggestion to Amazon, and the audit trail.

Routes
------
POST /suggestions/{id}/execute   Admin only — enqueue execution
GET  /suggestions/{id}/actions   Admin+User — every attempt, with the literal
                                 Amazon request/response
GET  /change-log                 Admin+User — what changed, when, old -> new

Approval deliberately does NOT execute. The spec is explicit: "Mandatory:
Rule -> Suggestion -> Human Review -> Apply. NO auto-apply in V1." Approving
marks intent; executing is a separate, deliberate act.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.modules.auth.models import User
from app.modules.execution.models import ChangeLog
from app.modules.execution.repository import ExecutionRepository
from app.modules.suggestions.models import Suggestion
from app.worker.execution_tasks import execute_suggestion

execution_router = APIRouter(tags=["execution"])


@execution_router.post("/suggestions/{suggestion_id}/execute")
def execute(
    suggestion_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> JSONResponse:
    """Admin only. Enqueue execution of an approved suggestion.

    Returns 202 immediately — the Amazon call happens in the worker. Poll
    GET /suggestions/{id}/actions for the outcome.
    """
    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).one_or_none()
    if suggestion is None:
        raise HTTPException(status_code=404, detail=f"Suggestion {suggestion_id} not found")

    if suggestion.status != "approved":
        # Refused here as well as in the service — a clear 409 to the caller
        # is more useful than a queued task that fails a second later.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Suggestion is '{suggestion.status}'. Only approved "
                    "suggestions can be executed."),
        )

    execute_suggestion.delay(str(suggestion_id), str(current_user.id))

    return JSONResponse(status_code=202, content={
        "message": "Execution queued — poll GET /suggestions/{id}/actions",
        "suggestion_id": str(suggestion_id),
        "status": "queued",
    })


@execution_router.get("/suggestions/{suggestion_id}/actions")
def list_actions(
    suggestion_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> JSONResponse:
    """Every attempt against this suggestion, newest first.

    Includes the literal Amazon request and response — this is the record
    that answers 'what exactly did we send, and what came back'.
    """
    rows = ExecutionRepository(db).actions_for(suggestion_id)
    return JSONResponse(content={
        "suggestion_id": str(suggestion_id),
        "actions": [{
            "id": str(r.id),
            "action": r.action,
            "performed_by": str(r.performed_by) if r.performed_by else None,
            "notes": r.notes,
            "amazon_api_request": r.amazon_api_request,
            "amazon_api_response": r.amazon_api_response,
            "amazon_api_status_code": r.amazon_api_status_code,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows],
    })


@execution_router.get("/change-log")
def list_change_log(
    profile_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> JSONResponse:
    """What actually changed on Amazon, newest first.

    Backs the Logs screen and answers the question the spec calls
    non-negotiable for trust: 'why did this bid change'.
    """
    q = db.query(ChangeLog)
    if profile_id:
        q = q.filter(ChangeLog.profile_id == profile_id)
    # The TOTAL, not len(rows). "count" used to mean "rows in this page", so a
    # caller fetching with limit=1 to be cheap — as the Dashboard tile does —
    # was told there had been 1 change to the account when there were 2.
    # A field named count has to mean the count.
    total = q.count()
    rows = q.order_by(ChangeLog.changed_at.desc()).limit(limit).all()

    return JSONResponse(content={
        "count": total,
        "returned": len(rows),
        "changes": [{
            "id": str(r.id),
            "profile_id": str(r.profile_id),
            "entity_type": r.entity_type,
            "entity_id": str(r.entity_id) if r.entity_id else None,
            "amazon_entity_id": r.amazon_entity_id,
            "field_changed": r.field_changed,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "suggestion_id": str(r.suggestion_id) if r.suggestion_id else None,
            "changed_by": str(r.changed_by) if r.changed_by else None,
            "source": r.source,
            "rolled_back_at": r.rolled_back_at.isoformat() if r.rolled_back_at else None,
            "changed_at": r.changed_at.isoformat() if r.changed_at else None,
        } for r in rows],
    })


@execution_router.post("/change-log/{change_id}/rollback")
def rollback_change(
    change_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> JSONResponse:
    """Admin only. Undo one executed change by writing its old value back.

    Runs inline rather than via the worker: a rollback is one short call and
    the operator is usually watching, so an immediate answer is more useful
    than a queued job they have to poll.
    """
    from app.modules.execution.service import RollbackService

    result = RollbackService(db).rollback(change_id, current_user.id)
    return JSONResponse(status_code=200 if result.get("ok") else 409, content=result)
