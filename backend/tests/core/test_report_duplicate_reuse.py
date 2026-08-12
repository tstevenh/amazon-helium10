"""A duplicate report request must reuse the report, not fail the sync.

Amazon deduplicates identical report requests and answers HTTP 425 with
"The Request is a duplicate of : <reportId>". Found on 2026-08-12 while
re-running a placement sync: both profiles failed, and the sync reported an
error while Amazon was already generating exactly the report we asked for.

This is not an edge case. A report takes 20-40 minutes, so ANY retry inside
Amazon's dedup window hits it — a sync re-triggered by hand, a scheduled sync
overlapping a manual one, or a retry after a network blip.
"""
import pytest

from app.core.amazon_reporting import _existing_report_id_from_duplicate


class FakeResponse:
    def __init__(self, payload=None, text="", raises=False):
        self.status_code = 425
        self._payload = payload
        self.text = text
        self._raises = raises

    def json(self):
        if self._raises:
            raise ValueError("not json")
        return self._payload


def test_report_id_is_extracted_from_amazons_message():
    """Amazon puts the id in prose, not in a field."""
    resp = FakeResponse({
        "code": "425",
        "detail": "The Request is a duplicate of : 4545ce53-6edf-45d2-8489-193ec9d8029c",
    })
    assert _existing_report_id_from_duplicate(resp) == "4545ce53-6edf-45d2-8489-193ec9d8029c"


@pytest.mark.parametrize("detail", [
    "The Request is a duplicate of : abc123def456abc7",
    "the request is a DUPLICATE OF: abc123def456abc7",
    "duplicate of abc123def456abc7",
])
def test_extraction_tolerates_wording_and_spacing_changes(detail):
    """The message is prose and Amazon may reword it."""
    assert _existing_report_id_from_duplicate(FakeResponse({"detail": detail})) \
        == "abc123def456abc7"


def test_falls_back_to_raw_text_when_the_body_is_not_json():
    resp = FakeResponse(
        text="The Request is a duplicate of : 2cfe3b4ae18d449f825e3d5c35061e10",
        raises=True,
    )
    assert _existing_report_id_from_duplicate(resp) == "2cfe3b4ae18d449f825e3d5c35061e10"


def test_unrecognised_message_returns_none_so_the_caller_still_raises():
    """Better a loud failure than silently polling a report id we invented."""
    assert _existing_report_id_from_duplicate(FakeResponse({"detail": "rate limited"})) is None
    assert _existing_report_id_from_duplicate(FakeResponse({})) is None
    assert _existing_report_id_from_duplicate(FakeResponse(text="", raises=True)) is None


def test_request_report_reuses_rather_than_raising_on_425():
    """Guards the branch, not just the parser."""
    import inspect

    from app.core import amazon_reporting

    src = inspect.getsource(amazon_reporting._request_report)
    assert "425" in src, "the duplicate case must be handled explicitly"
    dup_at = src.index("425")
    raise_at = src.index("_raise_for_amazon_error")
    assert dup_at < raise_at, (
        "the 425 reuse branch must come before _raise_for_amazon_error, or the "
        "duplicate is turned into a failure before it can be reused"
    )
