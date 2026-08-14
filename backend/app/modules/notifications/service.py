"""Producing and recording notifications.

The existing `send_alert` in app/worker/health.py posts to a webhook and logs
to stderr when none is configured. That was not enough: eight consecutive
failed syncs on this account went unnoticed for a week because stderr is not
somewhere anyone looks.

So every notification is written to notification_log first and delivered
second. `logged_only` is a first-class outcome, not an error — it means the app
noticed something and had nowhere to say it. The Notifications screen reads
that table, so the app can tell you what it noticed even with no webhook set
up at all.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone as tz
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.notifications.models import NotificationLog

logger = logging.getLogger(__name__)

DELIVERED = "delivered"
FAILED = "failed"
LOGGED_ONLY = "logged_only"

EVENT_SYNC_FAILED = "sync_failed"
EVENT_SYNC_STALE = "sync_stale"
EVENT_SUGGESTIONS_PENDING = "suggestions_pending"
EVENT_EXECUTION_FAILED = "execution_failed"
EVENT_DAYPARTING_FAILED = "dayparting_failed"
EVENT_DAILY_DIGEST = "daily_digest"


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _recent_duplicate(self, event_type: str, subject: str) -> Optional[NotificationLog]:
        """The most recent identical notification inside the dedupe window.

        (event_type, subject) is the key rather than the body: health subjects
        carry the counts ("2 failed, 1 stale"), so a subject that is unchanged
        means the situation is unchanged, while a situation that worsens
        changes the counts and alerts again immediately.
        """
        if settings.notification_dedupe_minutes <= 0:
            return None
        cutoff = datetime.now(tz.utc) - timedelta(minutes=settings.notification_dedupe_minutes)
        return (
            self.db.query(NotificationLog)
            .filter(
                NotificationLog.event_type == event_type,
                NotificationLog.subject == subject[:300],
                NotificationLog.sent_at >= cutoff,
            )
            .order_by(NotificationLog.sent_at.desc())
            .first()
        )

    def notify(
        self,
        event_type: str,
        subject: str,
        body: str,
        payload: Optional[dict[str, Any]] = None,
        dedupe: bool = True,
    ) -> NotificationLog:
        """Record a notification, then try to deliver it.

        Recording first is deliberate: if delivery raises, the fact that the
        app noticed still survives.

        Repeats of an identical (event_type, subject) inside
        notification_dedupe_minutes are suppressed entirely — not recorded and
        not delivered. Health checks re-report conditions that persist, so a
        single stale account produced 47 identical rows in one day. Alerting
        that cries wolf gets muted, and a muted channel fails silently, which
        is what this whole module exists to prevent. Pass dedupe=False for
        notifications that must always land regardless of repetition.
        """
        if dedupe:
            existing = self._recent_duplicate(event_type, subject)
            if existing is not None:
                logger.info(
                    "[notify] suppressed duplicate %s within %dm: %s",
                    event_type, settings.notification_dedupe_minutes, subject,
                )
                return existing

        row = NotificationLog(
            event_type=event_type,
            channel="slack" if settings.alert_webhook_url else None,
            subject=subject[:300],
            body=body,
            payload=payload,
            delivery_status=LOGGED_ONLY,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)

        if not settings.alert_webhook_url:
            # Not a failure: nothing was configured to deliver to.
            logger.warning("[notify] %s (no webhook configured): %s", event_type, subject)
            return row

        # Imported here to avoid a circular import: health imports nothing from
        # this module, and this module only needs its transport.
        from app.worker.health import send_alert

        try:
            ok = send_alert(f"*{subject}*\n{body}")
            row.delivery_status = DELIVERED if ok else FAILED
            if not ok:
                row.error_message = "webhook returned a non-2xx response"
        except Exception as exc:
            row.delivery_status = FAILED
            row.error_message = str(exc)[:1000]
        self.db.commit()
        self.db.refresh(row)
        return row

    # ── Daily digest ───────────────────────────────────────────────────────

    def build_daily_digest(self, for_date: Optional[date] = None) -> dict[str, Any]:
        """Counts for the last 24 hours, plus anything currently unhealthy.

        Spec §4.3 asked for "pending/approved/executed counts". Sync health is
        included because a digest that says "3 suggestions pending" while every
        sync has failed for a week would be actively misleading — the numbers
        would be stale and the digest would not say so.
        """
        from app.modules.execution.models import ChangeLog
        from app.modules.suggestions.models import Suggestion
        from app.modules.sync_jobs.models import SyncJob
        from app.modules.sync_jobs.repository import (
            JOB_STATUS_SUCCESS, UNHEALTHY_STATUSES,
        )

        now = datetime.now(tz.utc)
        since = now - timedelta(hours=24)

        def count_status(status: str) -> int:
            return (
                self.db.query(func.count(Suggestion.id))
                .filter(Suggestion.status == status)
                .scalar() or 0
            )

        approved_recently = (
            self.db.query(func.count(Suggestion.id))
            .filter(Suggestion.status == "approved", Suggestion.resolved_at >= since)
            .scalar() or 0
        )
        changes_recently = (
            self.db.query(func.count(ChangeLog.id))
            .filter(ChangeLog.changed_at >= since)
            .scalar() or 0
        )
        failed_syncs = (
            self.db.query(func.count(SyncJob.id))
            .filter(SyncJob.status.in_(UNHEALTHY_STATUSES),
                    SyncJob.created_at >= since)
            .scalar() or 0
        )
        last_ok = (
            self.db.query(SyncJob)
            .filter(SyncJob.status == JOB_STATUS_SUCCESS,
                    SyncJob.finished_at.isnot(None))
            .order_by(SyncJob.finished_at.desc())
            .first()
        )
        hours_since_sync = (
            (now - last_ok.finished_at).total_seconds() / 3600
            if last_ok and last_ok.finished_at else None
        )

        return {
            "pending": count_status("pending"),
            "approved_total": count_status("approved"),
            "approved_24h": approved_recently,
            "executed_total": count_status("executed"),
            "changes_24h": changes_recently,
            "failed_syncs_24h": failed_syncs,
            "hours_since_successful_sync": (
                round(hours_since_sync, 1) if hours_since_sync is not None else None
            ),
            "writes_enabled": settings.amazon_write_enabled,
        }

    def format_daily_digest(self, d: dict[str, Any]) -> tuple[str, str]:
        """Turn the digest into something a person reads in three seconds."""
        stale_hours = d["hours_since_successful_sync"]
        data_is_stale = stale_hours is None or stale_hours > settings.sync_stale_after_hours

        if data_is_stale:
            headline = "PPC OS: data may be out of date"
        elif d["pending"]:
            headline = f"PPC OS: {d['pending']} suggestions waiting for review"
        else:
            headline = "PPC OS: nothing needs attention"

        lines = []
        if stale_hours is None:
            lines.append("• No sync has ever completed successfully.")
        else:
            lines.append(f"• Last successful sync: {stale_hours:.0f}h ago"
                         + ("  ← stale" if data_is_stale else ""))
        if d["failed_syncs_24h"]:
            lines.append(f"• Syncs failed or partial in the last 24h: {d['failed_syncs_24h']}")
        lines.append(f"• Suggestions waiting: {d['pending']}")
        if d["approved_24h"]:
            lines.append(f"• Approved in the last 24h: {d['approved_24h']}")
        if d["changes_24h"]:
            lines.append(f"• Changes sent to Amazon in the last 24h: {d['changes_24h']}")
        else:
            lines.append("• No changes were sent to Amazon.")
        if not d["writes_enabled"]:
            # Worth stating: otherwise "0 changes" reads as "nothing needed
            # doing" rather than "we could not have done anything".
            lines.append("• Writes to Amazon are switched off.")

        return headline, "\n".join(lines)

    def send_daily_digest(self) -> NotificationLog:
        data = self.build_daily_digest()
        subject, body = self.format_daily_digest(data)
        return self.notify(EVENT_DAILY_DIGEST, subject, body, payload=data)
