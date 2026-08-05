"""Shared test fixtures.

These tests never touch Postgres or Amazon. `fake_requests` replaces the
`requests` functions that app.core.amazon_ads and app.core.amazon_reporting
call, so we control exactly what "Amazon" returns.
"""
import os

# Must be set before importing anything under app.* — Settings has no default
# for database_url or jwt_secret_key, so import would raise ValidationError.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://t:t@localhost:5432/t")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("AMAZON_CLIENT_ID", "test-client-id")
os.environ.setdefault("AMAZON_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("AMAZON_MOCK_MODE", "false")

import pytest


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status: int, json_body):
        self.status_code = status
        self._json = json_body
        self.text = str(json_body)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        return self._json


class FakeRequests:
    """Queues canned responses matched by (method, url substring).

    Responses are consumed in FIFO order per matching key. If a request
    arrives with no queued response, the test fails loudly rather than
    silently returning something plausible.
    """

    def __init__(self):
        self._queue: list[tuple[str, str, object]] = []
        self.calls: list[tuple[str, str]] = []

    def queue_response(self, method: str, url_substring: str, status: int, json_body):
        self._queue.append((method.upper(), url_substring, FakeResponse(status, json_body)))

    def queue_exception(self, method: str, url_substring: str, exc: Exception):
        self._queue.append((method.upper(), url_substring, exc))

    def _handle(self, method: str, url: str):
        self.calls.append((method, url))
        for i, (m, sub, result) in enumerate(self._queue):
            if m == method and sub in url:
                self._queue.pop(i)
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"Unexpected {method} {url} — no queued response")

    def post(self, url, **kwargs):
        return self._handle("POST", url)

    def get(self, url, **kwargs):
        return self._handle("GET", url)

    def request(self, method, url, **kwargs):
        return self._handle(str(method).upper(), url)


@pytest.fixture
def fake_requests(monkeypatch):
    fake = FakeRequests()
    from app.core import amazon_ads, amazon_reporting

    for mod in (amazon_ads, amazon_reporting):
        monkeypatch.setattr(mod.requests, "post", fake.post)
        monkeypatch.setattr(mod.requests, "get", fake.get)
        monkeypatch.setattr(mod.requests, "request", fake.request)
    return fake


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Retry and poll loops must not actually sleep during tests."""
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda _s: None)
