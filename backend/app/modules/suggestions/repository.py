"""Repository for suggestions (Sprint 2.5)."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.suggestions.models import Suggestion


class SuggestionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_profile(
        self,
        profile_id: uuid.UUID,
        status: Optional[str] = None,
        kind:   Optional[str] = None,
        confidence_min: Optional[int] = None,
        confidence_max: Optional[int] = None,
        sort_by: Optional[str] = None,
    ) -> list[Suggestion]:
        q = self.db.query(Suggestion).filter(Suggestion.profile_id == profile_id)
        if status and status != "all":
            q = q.filter(Suggestion.status == status)
        if kind and kind != "all":
            q = q.filter(Suggestion.kind == kind)
        if confidence_min is not None:
            q = q.filter(Suggestion.confidence_score >= confidence_min)
        if confidence_max is not None:
            q = q.filter(Suggestion.confidence_score <= confidence_max)

        # Sorting
        if sort_by == "confidence":
            q = q.order_by(Suggestion.confidence_score.desc(), Suggestion.created_at.desc())
        elif sort_by == "spend":
            q = q.order_by(Suggestion.total_spend.desc(), Suggestion.created_at.desc())
        elif sort_by == "sales":
            q = q.order_by(Suggestion.total_sales.desc(), Suggestion.created_at.desc())
        else:
            q = q.order_by(Suggestion.created_at.desc())

        return q.all()

    def get_by_id(self, suggestion_id: uuid.UUID) -> Optional[Suggestion]:
        return self.db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()

    def get_by_ids(self, ids: list[uuid.UUID]) -> list[Suggestion]:
        if not ids:
            return []
        return self.db.query(Suggestion).filter(Suggestion.id.in_(ids)).all()

    def pending_exists(
        self,
        profile_id: uuid.UUID,
        search_term: str,
        suggestion_type: str,
    ) -> bool:
        """Deduplication key: (profile_id, search_term, suggestion_type) with status=pending."""
        return (
            self.db.query(Suggestion)
            .filter_by(
                profile_id=profile_id,
                search_term=search_term,
                suggestion_type=suggestion_type,
                status="pending",
            )
            .first()
        ) is not None

    def create(self, data: dict) -> Suggestion:
        s = Suggestion(**data)
        self.db.add(s)
        self.db.flush()
        return s

    def resolve(
        self,
        suggestion: Suggestion,
        new_status: str,
        resolved_by: uuid.UUID,
    ) -> Suggestion:
        suggestion.status      = new_status
        suggestion.resolved_by = resolved_by
        suggestion.resolved_at = datetime.utcnow()
        suggestion.updated_at  = datetime.utcnow()
        self.db.flush()
        return suggestion

    def bulk_resolve(
        self,
        suggestions: list[Suggestion],
        new_status: str,
        resolved_by: uuid.UUID,
    ) -> tuple[int, int]:
        """Resolve a list of suggestions. Returns (resolved_count, skipped_count)."""
        resolved = 0
        skipped  = 0
        now = datetime.utcnow()
        for s in suggestions:
            if s.status != "pending":
                skipped += 1
                continue
            s.status      = new_status
            s.resolved_by = resolved_by
            s.resolved_at = now
            s.updated_at  = now
            resolved += 1
        self.db.flush()
        return resolved, skipped

    def count_pending(self, profile_id: uuid.UUID) -> int:
        return (
            self.db.query(Suggestion)
            .filter_by(profile_id=profile_id, status="pending")
            .count()
        )
