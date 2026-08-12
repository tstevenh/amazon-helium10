"""The digest has to be readable and honest.

A digest nobody reads is worse than none, because it creates the impression of
oversight. The tests below are about the two ways it could mislead: hiding that
data is stale behind a cheerful headline, and reporting "0 changes" without
saying that changes were impossible.
"""
from datetime import date

import pytest

from app.config import settings
from app.modules.notifications.service import (
    DELIVERED,
    FAILED,
    LOGGED_ONLY,
    NotificationService,
)


def fmt(**over):
    """Format a digest from a full payload with selected fields overridden."""
    data = {
        "pending": 0, "approved_total": 0, "approved_24h": 0,
        "executed_total": 0, "changes_24h": 0, "failed_syncs_24h": 0,
        "hours_since_successful_sync": 1.0, "writes_enabled": True,
    }
    data.update(over)
    svc = NotificationService.__new__(NotificationService)   # no DB needed
    return svc.format_daily_digest(data)


def test_stale_data_leads_the_headline_even_with_work_waiting():
    """Stale data outranks everything.

    "12 suggestions waiting" on week-old numbers invites someone to act on
    figures that no longer describe the account.
    """
    subject, _ = fmt(pending=12, hours_since_successful_sync=200)
    assert "out of date" in subject.lower()
    assert "12" not in subject


def test_never_synced_is_not_reported_as_healthy():
    subject, body = fmt(hours_since_successful_sync=None)
    assert "out of date" in subject.lower()
    assert "No sync has ever completed successfully" in body


def test_quiet_account_says_so_plainly():
    subject, _ = fmt()
    assert "nothing needs attention" in subject.lower()


def test_pending_count_appears_when_data_is_fresh():
    subject, _ = fmt(pending=13)
    assert "13" in subject


def test_zero_changes_explains_itself_when_writes_are_off():
    """Otherwise "no changes were sent" reads as "nothing needed doing"."""
    _, body = fmt(changes_24h=0, writes_enabled=False)
    assert "No changes were sent" in body
    assert "switched off" in body


def test_zero_changes_with_writes_on_does_not_claim_writes_are_off():
    _, body = fmt(changes_24h=0, writes_enabled=True)
    assert "No changes were sent" in body
    assert "switched off" not in body


def test_failed_syncs_are_surfaced_in_the_body():
    _, body = fmt(failed_syncs_24h=8)
    assert "8" in body


def test_body_never_hides_the_sync_age():
    """Every digest states when data was last refreshed, healthy or not."""
    for hours in (0.5, 5, 100):
        _, body = fmt(hours_since_successful_sync=hours)
        assert "Last successful sync" in body


def test_stale_threshold_follows_configuration():
    """The digest must agree with the Sync Monitor about what "stale" means."""
    limit = settings.sync_stale_after_hours
    fresh_subject, _ = fmt(hours_since_successful_sync=limit - 0.5)
    stale_subject, _ = fmt(hours_since_successful_sync=limit + 0.5)

    assert "out of date" not in fresh_subject.lower()
    assert "out of date" in stale_subject.lower()


def test_delivery_statuses_match_the_database_constraint():
    """ck_notification_log_delivery_status permits exactly these three."""
    assert {DELIVERED, FAILED, LOGGED_ONLY} == {"delivered", "failed", "logged_only"}


def test_logged_only_is_distinct_from_failed():
    """They mean different things and must not be conflated.

    'failed' is a webhook that rejected us — someone should look. 'logged_only'
    is no webhook configured at all — expected, and fixed by configuration.
    """
    assert LOGGED_ONLY != FAILED


def test_email_channel_is_not_offered_by_the_api():
    """The spec lists email, but this app has no mail transport.

    Accepting it would create a rule that silently never delivers, which is
    worse than refusing it.
    """
    from app.modules.notifications.router import RuleIn

    field = RuleIn.model_fields["channel"]
    # Literal["slack"] — email must not be an accepted input value.
    assert "email" not in str(field.annotation)
