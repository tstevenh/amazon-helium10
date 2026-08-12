"""Notifications API.

Read-heavy on purpose. The valuable half of this feature is the log: it lets
the app answer "did anything tell us?" without a webhook being configured.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.notifications.models import NotificationLog, NotificationRule
from app.modules.notifications.service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])

_EVENT_TYPES = ("sync_failed", "sync_stale", "suggestions_pending",
                "execution_failed", "dayparting_failed", "daily_digest")


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:              uuid.UUID
    event_type:      str
    channel:         Optional[str]
    subject:         Optional[str]
    body:            Optional[str]
    delivery_status: str
    error_message:   Optional[str]
    read_at:         Optional[datetime]
    sent_at:         datetime


class LogPage(BaseModel):
    items: list[LogOut]
    unread: int
    # Surfaced so the screen can explain 'logged_only' rather than showing a
    # status nobody can interpret.
    webhook_configured: bool


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:               uuid.UUID
    event_type:       str
    channel:          str
    threshold_config: dict
    is_active:        bool
    created_at:       datetime


class RuleIn(BaseModel):
    event_type: Literal[_EVENT_TYPES]  # type: ignore[valid-type]
    # 'email' exists in the spec and the DB constraint, but this app has no
    # mail transport. Accepting it would create a rule that silently never
    # delivers, so it is refused here until a transport exists.
    channel: Literal["slack"] = "slack"
    threshold_config: dict = Field(default_factory=dict)


@router.get("", response_model=LogPage)
def list_notifications(
    limit: int = Query(50, le=200),
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(NotificationLog)
    if unread_only:
        q = q.filter(NotificationLog.read_at.is_(None))
    items = q.order_by(NotificationLog.sent_at.desc()).limit(limit).all()
    unread = (
        db.query(func.count(NotificationLog.id))
        .filter(NotificationLog.read_at.is_(None))
        .scalar() or 0
    )
    return LogPage(
        items=[LogOut.model_validate(i) for i in items],
        unread=unread,
        webhook_configured=bool(settings.alert_webhook_url),
    )


@router.post("/{notification_id}/read", status_code=204)
def mark_read(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    row = db.query(NotificationLog).filter(
        NotificationLog.id == notification_id).first()
    if row is None:
        raise HTTPException(404, "Notification not found")
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        db.commit()


@router.post("/read-all", status_code=204)
def mark_all_read(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    db.query(NotificationLog).filter(NotificationLog.read_at.is_(None)).update(
        {NotificationLog.read_at: datetime.now(timezone.utc)},
        synchronize_session=False,
    )
    db.commit()


@router.post("/test-digest", response_model=LogOut)
def send_test_digest(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Send the digest now.

    Exists so an operator can confirm a new webhook works without waiting a
    day, and see exactly what their team will receive.
    """
    return NotificationService(db).send_daily_digest()


@router.get("/digest-preview")
def digest_preview(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """What the digest would say right now, without sending or logging it."""
    svc = NotificationService(db)
    data = svc.build_daily_digest()
    subject, body = svc.format_daily_digest(data)
    return {"subject": subject, "body": body, "data": data}


@router.get("/rules", response_model=list[RuleOut])
def list_rules(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return (
        db.query(NotificationRule)
        .filter(NotificationRule.deleted_at.is_(None))
        .order_by(NotificationRule.created_at.desc())
        .all()
    )


@router.post("/rules", response_model=RuleOut, status_code=201)
def create_rule(
    body: RuleIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = NotificationRule(
        event_type=body.event_type, channel=body.channel,
        threshold_config=body.threshold_config, created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    row = db.query(NotificationRule).filter(
        NotificationRule.id == rule_id,
        NotificationRule.deleted_at.is_(None),
    ).first()
    if row is None:
        raise HTTPException(404, "Rule not found")
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()
