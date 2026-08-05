"""The report poll ceiling must come from settings, not a hardcoded constant."""
import pytest

from app.config import settings
from app.core import amazon_reporting


def test_poll_ceiling_is_configurable(monkeypatch, fake_requests):
    """With the ceiling set to 2, exactly 2 polls happen before giving up."""
    monkeypatch.setattr(settings, "amazon_report_poll_max_attempts", 2)
    for _ in range(5):
        fake_requests.queue_response("GET", "/reporting/reports/", 200, {"status": "PENDING"})

    with pytest.raises(RuntimeError, match="did not complete"):
        amazon_reporting._poll_report("tok", 123, "report-abc")

    polls = [c for c in fake_requests.calls if "/reporting/reports/" in c[1]]
    assert len(polls) == 2, f"expected 2 polls, saw {len(polls)}"


def test_poll_returns_on_completed(fake_requests):
    fake_requests.queue_response("GET", "/reporting/reports/", 200, {"status": "PENDING"})
    fake_requests.queue_response(
        "GET", "/reporting/reports/", 200,
        {"status": "COMPLETED", "url": "https://s3.example/report.gz"},
    )

    result = amazon_reporting._poll_report("tok", 123, "report-abc")

    assert result["status"] == "COMPLETED"


def test_poll_raises_immediately_on_failure_status(fake_requests):
    """A FAILURE from Amazon must not burn the whole ceiling waiting."""
    from app.core.amazon_ads import AmazonApiError

    fake_requests.queue_response(
        "GET", "/reporting/reports/", 200,
        {"status": "FAILURE", "statusDetails": "bad columns"},
    )

    with pytest.raises(AmazonApiError, match="FAILURE"):
        amazon_reporting._poll_report("tok", 123, "report-abc")


def test_default_ceiling_allows_at_least_two_hours():
    """Regression guard: 180 polls (~40 min) was too short for real accounts.

    Measured 2026-08-04 on profile 89389798686160: the 2-day campaign report
    took 40 minutes (poll 173/180) and the ad-group and keyword reports both
    exceeded the ceiling and were abandoned every single time.
    """
    total_seconds = (
        settings.amazon_report_poll_max_attempts * settings.amazon_report_poll_interval_sec
    )
    assert total_seconds >= 7200, f"ceiling is only {total_seconds}s — too short"
