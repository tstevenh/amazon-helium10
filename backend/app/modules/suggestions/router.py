"""Suggestions router (Sprint 2.5).

Routes:
  GET  /suggestions                     — list suggestions for a profile
  POST /suggestions/generate            — run suggestion engine
  POST /suggestions/bulk-approve        — bulk approve pending suggestions
  POST /suggestions/bulk-reject         — bulk reject pending suggestions
  POST /suggestions/{id}/approve        — approve a single suggestion
  POST /suggestions/{id}/reject         — reject a single suggestion
"""
from __future__ import annotations
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.audit_log.repository import AuditLogRepository
from app.modules.suggestions.repository import SuggestionRepository
from app.modules.suggestions.schemas import (
    BulkResolveRequest,
    BulkResolveResponse,
    GenerateResponse,
    ResolveRequest,
    SuggestionResponse,
)
from app.modules.suggestions.service import SuggestionEngine

suggestions_router = APIRouter(prefix="/suggestions", tags=["suggestions"])


@suggestions_router.get("", response_model=list[SuggestionResponse])
def list_suggestions(
    profile_id:     uuid.UUID      = Query(...),
    status_filter:  Optional[str]  = Query(None, alias="status"),
    kind:           Optional[str]  = Query(None),
    confidence_min: Optional[int]  = Query(None),
    confidence_max: Optional[int]  = Query(None),
    sort_by:        Optional[str]  = Query(None),   # newest|confidence|spend|sales
    _user: User    = Depends(get_current_user),
    db:    Session = Depends(get_db),
) -> list[SuggestionResponse]:
    repo = SuggestionRepository(db)
    rows = repo.get_by_profile(
        profile_id=profile_id,
        status=status_filter,
        kind=kind,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        sort_by=sort_by,
    )
    return [SuggestionResponse.model_validate(r) for r in rows]


@suggestions_router.post("/generate", response_model=GenerateResponse)
def generate_suggestions(
    profile_id: uuid.UUID = Query(...),
    user:  User    = Depends(get_current_user),
    db:    Session = Depends(get_db),
) -> GenerateResponse:
    engine = SuggestionEngine(db)
    n = engine.generate_for_profile(profile_id=profile_id, user_id=user.id)
    db.commit()
    return GenerateResponse(profile_id=str(profile_id), suggestions_generated=n)


# ── Bulk actions (must be declared BEFORE /{suggestion_id}/…) ─────────────────

@suggestions_router.post("/bulk-approve", response_model=BulkResolveResponse)
def bulk_approve(
    body: BulkResolveRequest,
    user: User    = Depends(get_current_user),
    db:   Session = Depends(get_db),
) -> BulkResolveResponse:
    repo        = SuggestionRepository(db)
    audit_repo  = AuditLogRepository(db)
    suggestions = repo.get_by_ids(body.ids)

    resolved, skipped = repo.bulk_resolve(suggestions, "approved", user.id)

    # Log one audit entry summarising the bulk action
    if resolved > 0:
        audit_repo.create(
            user_id=user.id,
            entity_type="suggestion",
            entity_id=user.id,          # no single entity — use user id as placeholder
            action="bulk_approved",
            reason=body.reason,
            extra_data={
                "count":      resolved,
                "ids":        [str(i) for i in body.ids],
                "skipped":    skipped,
            },
        )

    db.commit()
    return BulkResolveResponse(resolved=resolved, skipped=skipped)


@suggestions_router.post("/bulk-reject", response_model=BulkResolveResponse)
def bulk_reject(
    body: BulkResolveRequest,
    user: User    = Depends(get_current_user),
    db:   Session = Depends(get_db),
) -> BulkResolveResponse:
    repo        = SuggestionRepository(db)
    audit_repo  = AuditLogRepository(db)
    suggestions = repo.get_by_ids(body.ids)

    resolved, skipped = repo.bulk_resolve(suggestions, "rejected", user.id)

    if resolved > 0:
        audit_repo.create(
            user_id=user.id,
            entity_type="suggestion",
            entity_id=user.id,
            action="bulk_rejected",
            reason=body.reason,
            extra_data={
                "count":   resolved,
                "ids":     [str(i) for i in body.ids],
                "skipped": skipped,
            },
        )

    db.commit()
    return BulkResolveResponse(resolved=resolved, skipped=skipped)


# ── Single-item actions ────────────────────────────────────────────────────────

@suggestions_router.post("/{suggestion_id}/approve", response_model=SuggestionResponse)
def approve_suggestion(
    suggestion_id: uuid.UUID,
    body: ResolveRequest = ResolveRequest(),
    user: User    = Depends(get_current_user),
    db:   Session = Depends(get_db),
) -> SuggestionResponse:
    repo = SuggestionRepository(db)
    sugg = repo.get_by_id(suggestion_id)
    if not sugg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")
    if sugg.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Suggestion is already {sugg.status}")

    repo.resolve(sugg, "approved", user.id)
    AuditLogRepository(db).create(
        user_id=user.id,
        entity_type="suggestion",
        entity_id=sugg.id,
        action="approved",
        reason=body.reason,
        extra_data={"kind": sugg.kind, "search_term": sugg.search_term},
    )
    db.commit()
    db.refresh(sugg)
    return SuggestionResponse.model_validate(sugg)


@suggestions_router.post("/{suggestion_id}/reject", response_model=SuggestionResponse)
def reject_suggestion(
    suggestion_id: uuid.UUID,
    body: ResolveRequest = ResolveRequest(),
    user: User    = Depends(get_current_user),
    db:   Session = Depends(get_db),
) -> SuggestionResponse:
    repo = SuggestionRepository(db)
    sugg = repo.get_by_id(suggestion_id)
    if not sugg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")
    if sugg.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Suggestion is already {sugg.status}")

    repo.resolve(sugg, "rejected", user.id)
    AuditLogRepository(db).create(
        user_id=user.id,
        entity_type="suggestion",
        entity_id=sugg.id,
        action="rejected",
        reason=body.reason,
        extra_data={"kind": sugg.kind, "search_term": sugg.search_term},
    )
    db.commit()
    db.refresh(sugg)
    return SuggestionResponse.model_validate(sugg)
