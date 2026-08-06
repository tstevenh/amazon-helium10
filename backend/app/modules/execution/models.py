"""Execution audit models.

Two tables from the spec's V1 list that were never created:

  suggestion_actions — append-only. Every execution attempt, with the literal
    Amazon request and response. Never updated, never deleted: if the process
    dies mid-call there is still a record that we tried.

  change_log — old -> new per field. This is what makes rollback possible; a
    row here means "this really changed on Amazon".
"""
import uuid

from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class SuggestionAction(Base):
    __tablename__ = "suggestion_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suggestion_id = Column(
        UUID(as_uuid=True), ForeignKey("suggestions.id", ondelete="CASCADE"), nullable=False
    )
    action = Column(String(30), nullable=False)
    # NULL means the system acted rather than a person.
    performed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)
    amazon_api_request = Column(JSONB, nullable=True)
    amazon_api_response = Column(JSONB, nullable=True)
    amazon_api_status_code = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ChangeLog(Base):
    __tablename__ = "change_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id = Column(
        UUID(as_uuid=True), ForeignKey("ads_profiles.id", ondelete="CASCADE"), nullable=False
    )
    entity_type = Column(String(20), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    # Kept alongside our UUID so a rollback can address Amazon directly even
    # if the local row is soft-deleted later.
    amazon_entity_id = Column(BigInteger, nullable=True)
    field_changed = Column(String(50), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    suggestion_id = Column(
        UUID(as_uuid=True), ForeignKey("suggestions.id", ondelete="SET NULL"), nullable=True
    )
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    source = Column(String(30), nullable=False)
    rolled_back_at = Column(DateTime(timezone=True), nullable=True)
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
