# PPC OS Sync Honesty & Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Amazon sync layer tell the truth about failures, and stop losing data to transient network errors and a too-short report-poll ceiling.

**Architecture:** The Amazon client functions in `app/core/` currently catch every exception, log a warning, and return partial or empty lists. Callers therefore cannot distinguish "Amazon returned nothing" from "Amazon failed". We introduce a `PartialFetchError` that carries both the successfully-fetched items *and* the list of failures, so the service layer can persist what succeeded, skip destructive soft-deletes, and surface errors in the API response. We then add bounded retry-with-backoff to the paginated fetchers and make the report-poll ceiling configurable.

**Tech Stack:** Python 3.12, FastAPI 0.111, SQLAlchemy 2.0 (sync/psycopg2), pytest (new), Docker Compose, PostgreSQL 16.

## Global Constraints

Copied verbatim from the constraints the team established for this project:

- "No write operations to Amazon Ads. Read-only only."
- "Rules never apply Amazon changes. Rules only create suggestions."
- "Do NOT hardcode secrets"
- "Do NOT modify historical migrations"
- "Do NOT redesign architecture/database"
- "All real mode errors must be readable. Do not return generic 500 when Amazon rejects credentials."
- "Do not expose secrets."
- No new runtime dependencies beyond `pytest` in this plan. The background worker (Redis/ARQ) belongs to Plan 2.
- `AMAZON_MOCK_MODE=false` is the working configuration; mock mode must keep working unchanged.

## Scope

This plan covers **Phase 0 (make failures visible)** and **Phase 1 (stop losing data)** only.

**Deliberately out of scope**, to be covered by a second plan once this one lands:

- Background worker (Redis + ARQ/Celery), `sync_jobs` table wiring, UI status polling
- Scheduler for automatic periodic syncs
- Frontend changes
- The CA profile's Amazon-side HTTP 502 (not a code problem)

This plan produces working, independently valuable software: after it, a sync
that fails **says so**, and transient failures no longer silently discard data.

## Observed Behaviour This Plan Fixes

Measured against the live US profile `89389798686160` on 2026-08-04:

| Observation | Evidence |
|---|---|
| 215,000 keywords silently lost | `SP keywords v3 fetch failed ... RemoteDisconnected` → `sync_targets done: upserted=16680` with HTTP 200 |
| 2 of 3 reports failed, API said "complete" | `"Performance sync complete: 10 campaign rows, 0 ad group rows, 0 target rows"` |
| Report poll ceiling too short | `Report 42d83809 did not complete after 180 polls` (180 polls ≈ 40 min wall clock) |
| Amazon report latency is highly variable | Identical 2-day campaign report: 23 min one run, 40 min the next |
| Upstream failure cascades silently | CA profile: 9,415 keywords fetched, `skipped=9415`, no error surfaced |

## File Structure

**Created:**

- `.gitignore` — must exist before the first commit; excludes `.env`, `__pycache__`, `.next`, `node_modules`
- `backend/pytest.ini` — pytest configuration and import path
- `backend/tests/__init__.py` — empty, makes `tests` a package
- `backend/tests/conftest.py` — shared fixtures: a fake `requests` transport and a settings override
- `backend/tests/core/__init__.py` — empty
- `backend/tests/core/test_amazon_ads_errors.py` — Phase 0: fetch failures must raise, not swallow
- `backend/tests/core/test_amazon_ads_retry.py` — Phase 1: retry behaviour on transient errors
- `backend/tests/core/test_amazon_reporting_poll.py` — Phase 1: configurable poll ceiling

**Modified:**

- `backend/app/core/amazon_ads.py` — add `PartialFetchError`; stop swallowing in `list_campaigns` / `list_ad_groups` / `list_targets`; add retry to `_post_list_paginated` / `_get_list_paginated_sb`
- `backend/app/core/amazon_reporting.py:76-77` — poll ceiling from settings instead of module constants
- `backend/app/config.py` — three new settings with defaults
- `backend/app/modules/campaigns/service.py` — catch `PartialFetchError`, persist partial data, skip soft-delete, return `errors`
- `backend/app/modules/performance/service.py` — collect per-level failures, return them
- `backend/app/modules/campaigns/schemas.py` and `app/modules/performance/schemas.py` — add `errors: list[str]` to sync responses
- `backend/requirements.txt` — add `pytest==8.3.2`

`amazon_ads.py` is already 934 lines and does three jobs (auth, listing, normalising). Splitting it is tempting but is a refactor, not a fix, and the Global Constraints forbid redesign. Leave the structure alone; keep changes surgical.

---

### Task 1: Safety net — version control and a test harness

Nothing else in this plan is safe or verifiable without this. `ppc-os` is
currently not a git repository and has zero tests.

**Files:**
- Create: `.gitignore`
- Create: `backend/pytest.ini`
- Create: `backend/tests/__init__.py`, `backend/tests/core/__init__.py`
- Create: `backend/tests/conftest.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Consumes: nothing
- Produces: `fake_requests` pytest fixture — a context object with
  `.queue_response(method: str, url_substring: str, status: int, json_body: dict)`
  and `.calls: list[tuple[str, str]]`. Every later task's tests use it.

- [ ] **Step 1: Write `.gitignore` BEFORE running git init**

`.env` contains a live `AMAZON_CLIENT_SECRET`, `FERNET_KEY` and `JWT_SECRET_KEY`.
It must never enter git history. Write this file first.

```gitignore
# Secrets — never commit
.env
*.env
!.env.example

# Python
__pycache__/
*.py[cod]
.pytest_cache/
.venv/

# Next.js / Node
node_modules/
.next/
frontend/.next/

# OS
.DS_Store
```

- [ ] **Step 2: Initialise the repository and verify `.env` is excluded**

```bash
cd /Users/tsth/Downloads/helium/ppc-os
git init
git add -A
git status --short | grep -E "^A.*\.env$" && echo "DANGER: .env staged" || echo "OK: .env excluded"
```

Expected: `OK: .env excluded`. If `.env` is staged, STOP and fix `.gitignore`
before committing anything.

- [ ] **Step 3: Commit the untouched baseline**

A commit of the code *as received* means every later change is a reviewable diff.

```bash
git commit -m "chore: baseline import of ppc-os as received from team"
```

- [ ] **Step 4: Add pytest to requirements**

Append to `backend/requirements.txt`:

```
# Testing
pytest==8.3.2
```

- [ ] **Step 5: Create `backend/pytest.ini`**

```ini
[pytest]
testpaths = tests
pythonpath = .
python_files = test_*.py
python_functions = test_*
addopts = -v --tb=short
```

- [ ] **Step 6: Create the package markers**

```bash
mkdir -p backend/tests/core
touch backend/tests/__init__.py backend/tests/core/__init__.py
```

- [ ] **Step 7: Create `backend/tests/conftest.py`**

`app.config.Settings` requires `database_url`, so importing app modules fails
without it. Set it before any app import. No real database is touched — these
are pure unit tests against the HTTP layer.

```python
"""Shared test fixtures.

These tests never touch Postgres or Amazon. `fake_requests` replaces the
`requests.post` / `requests.get` functions that app.core.amazon_ads and
app.core.amazon_reporting call, so we control exactly what "Amazon" returns.
"""
import os

# Must be set before importing anything under app.* — Settings has no default.
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


@pytest.fixture
def fake_requests(monkeypatch):
    fake = FakeRequests()
    from app.core import amazon_ads, amazon_reporting

    monkeypatch.setattr(amazon_ads.requests, "post", fake.post)
    monkeypatch.setattr(amazon_ads.requests, "get", fake.get)
    monkeypatch.setattr(amazon_reporting.requests, "post", fake.post)
    monkeypatch.setattr(amazon_reporting.requests, "get", fake.get)
    return fake


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Retry and poll loops must not actually sleep during tests."""
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda _s: None)
```

- [ ] **Step 8: Verify the harness runs and collects zero tests without error**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api sh -c "cd /app && pip install pytest==8.3.2 -q && python -m pytest tests -q"
```

Expected: `no tests ran` — and crucially **no import errors**. An
`ImportError` or `pydantic ValidationError` here means `conftest.py`'s env vars
are wrong; fix before proceeding.

- [ ] **Step 9: Commit**

```bash
git add .gitignore backend/pytest.ini backend/tests backend/requirements.txt
git commit -m "test: add pytest harness with fake Amazon HTTP transport"
```

---

### Task 2: `PartialFetchError` — make `list_campaigns` stop lying

**Files:**
- Modify: `backend/app/core/amazon_ads.py` (add exception class near `AmazonApiError` at line 109; rewrite `list_campaigns` at lines 717-770)
- Test: `backend/tests/core/test_amazon_ads_errors.py`

**Interfaces:**
- Consumes: `fake_requests` fixture from Task 1
- Produces:
  ```python
  class PartialFetchError(Exception):
      def __init__(self, message: str, items: list[dict], failures: list[str]) -> None: ...
      items: list[dict]      # rows successfully fetched before/despite failures
      failures: list[str]    # human-readable, one per failed sub-fetch
  ```
  `list_campaigns(access_token: str, profile_id: int) -> list[dict]` keeps its
  signature and still returns a plain list on full success. It raises
  `PartialFetchError` when any sub-fetch failed.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/core/test_amazon_ads_errors.py`:

```python
"""Phase 0: a failed sub-fetch must raise, never be swallowed into an empty list."""
import pytest

from app.core import amazon_ads
from app.core.amazon_ads import PartialFetchError


def _sp_campaign(cid: int) -> dict:
    return {
        "campaignId": str(cid),
        "name": f"Campaign {cid}",
        "state": "ENABLED",
        "targetingType": "MANUAL",
        "budget": {"budget": 10.0},
        "startDate": "2026-01-01",
    }


def test_list_campaigns_returns_plain_list_when_all_sources_succeed(fake_requests):
    fake_requests.queue_response("POST", "/sp/campaigns/list", 200, {"campaigns": [_sp_campaign(1)]})
    fake_requests.queue_response("POST", "/sb/v4/campaigns/list", 200, {"campaigns": []})

    result = amazon_ads.list_campaigns("tok", 123)

    assert len(result) == 1
    assert result[0]["amazon_campaign_id"] == 1


def test_list_campaigns_raises_when_sp_fetch_fails(fake_requests):
    """The old behaviour logged a warning and returned []. That is the bug."""
    fake_requests.queue_response("POST", "/sp/campaigns/list", 502, {"code": "SERVER_ERROR", "details": "boom"})
    fake_requests.queue_response("POST", "/sb/v4/campaigns/list", 200, {"campaigns": []})

    with pytest.raises(PartialFetchError) as excinfo:
        amazon_ads.list_campaigns("tok", 123)

    assert "SP campaigns" in str(excinfo.value)
    assert excinfo.value.failures, "failures must describe what went wrong"


def test_partial_fetch_error_preserves_successful_items(fake_requests):
    """SB succeeded, SP failed — the SB rows must not be thrown away."""
    fake_requests.queue_response("POST", "/sp/campaigns/list", 500, {"code": "X", "details": "y"})
    fake_requests.queue_response(
        "POST", "/sb/v4/campaigns/list", 200,
        {"campaigns": [{"campaignId": "77", "name": "SB", "state": "ENABLED", "budget": 5.0}]},
    )

    with pytest.raises(PartialFetchError) as excinfo:
        amazon_ads.list_campaigns("tok", 123)

    assert len(excinfo.value.items) == 1
    assert excinfo.value.items[0]["amazon_campaign_id"] == 77
    assert excinfo.value.items[0]["ad_product"] == "SB"


def test_connection_drop_mid_fetch_raises(fake_requests):
    """This is the bug that silently lost 215,000 keywords."""
    from requests.exceptions import ConnectionError as ReqConnectionError

    fake_requests.queue_exception("POST", "/sp/campaigns/list", ReqConnectionError("Remote end closed connection"))
    fake_requests.queue_response("POST", "/sb/v4/campaigns/list", 200, {"campaigns": []})

    with pytest.raises(PartialFetchError):
        amazon_ads.list_campaigns("tok", 123)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/core/test_amazon_ads_errors.py -q
```

Expected: FAIL — `ImportError: cannot import name 'PartialFetchError'`.

- [ ] **Step 3: Add `PartialFetchError` to `amazon_ads.py`**

Insert immediately after the `AmazonApiError` class (after line 128):

```python
class PartialFetchError(Exception):
    """Raised when one or more sub-fetches failed but others may have succeeded.

    Carries the rows that WERE retrieved so callers can persist them, plus a
    human-readable description of each failure so the API can surface it.

    Callers MUST NOT run soft-delete logic when this is raised: the item list
    is an incomplete view of Amazon's inventory, and deleting "missing" rows
    would destroy live data.
    """

    def __init__(self, message: str, items: list[dict[str, Any]], failures: list[str]) -> None:
        super().__init__(message)
        self.items = items
        self.failures = failures

    def __str__(self) -> str:
        return self.args[0]
```

- [ ] **Step 4: Rewrite `list_campaigns` to accumulate failures**

Replace the body of `list_campaigns` (lines 717-770). Keep the mock-mode
branch and both sub-fetches exactly as they are; only the `except` blocks and
the return change:

```python
def list_campaigns(access_token: str, profile_id: int) -> list[dict[str, Any]]:
    """
    Return all campaigns (SP v3 + SB v4) for a profile in normalised form.

    Raises PartialFetchError if any sub-fetch failed. The exception carries
    whatever was successfully fetched, so callers can persist partial data
    while still knowing the view is incomplete.
    """
    if settings.amazon_mock_mode:
        data = _MOCK_CAMPAIGNS.get(profile_id, [])
        logger.info("[amazon_ads] MOCK: list_campaigns profile=%s — %d campaigns", profile_id, len(data))
        return data

    campaigns: list[dict[str, Any]] = []
    failures: list[str] = []

    # --- Sponsored Products v3 ---
    try:
        headers = _ad_api_headers(access_token, profile_id, "application/vnd.spCampaign.v3+json")
        body: dict[str, Any] = {
            "stateFilter": {"include": ["ENABLED", "PAUSED", "ARCHIVED"]},
            "maxResults": 1000,
        }
        raw, _, _ = _post_list_paginated(
            f"{settings.amazon_api_base_url}/sp/campaigns/list",
            headers, body, "campaigns",
        )
        campaigns.extend(_normalize_sp_campaign_v3(c) for c in raw)
        logger.info("[amazon_ads] SP campaigns v3 profile=%s: %d campaigns", profile_id, len(raw))
    except Exception as exc:
        msg = f"SP campaigns fetch failed for profile {profile_id}: {exc}"
        logger.error("[amazon_ads] %s", msg)
        failures.append(msg)

    # --- Sponsored Brands v4 ---
    try:
        headers = _ad_api_headers(access_token, profile_id, "application/vnd.sbCampaignResource.v4+json")
        body = {
            "stateFilter": {"include": ["ENABLED", "PAUSED", "ARCHIVED"]},
            "maxResults": 100,  # SB v4 hard cap; SP v3 allows 1000
        }
        raw, _, _ = _post_list_paginated(
            f"{settings.amazon_api_base_url}/sb/v4/campaigns/list",
            headers, body, "campaigns",
        )
        campaigns.extend(_normalize_sb_campaign_v4(c) for c in raw)
        logger.info("[amazon_ads] SB campaigns v4 profile=%s: %d campaigns", profile_id, len(raw))
    except Exception as exc:
        msg = f"SB campaigns fetch failed for profile {profile_id}: {exc}"
        logger.error("[amazon_ads] %s", msg)
        failures.append(msg)

    if failures:
        raise PartialFetchError(
            f"Campaign fetch incomplete for profile {profile_id}: " + "; ".join(failures),
            campaigns,
            failures,
        )
    return campaigns
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/core/test_amazon_ads_errors.py -q
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/amazon_ads.py backend/tests/core/test_amazon_ads_errors.py
git commit -m "fix: list_campaigns raises PartialFetchError instead of swallowing failures"
```

---

### Task 3: Same treatment for `list_ad_groups` and `list_targets`

`list_targets` is the function that lost 215,000 keywords, so this is the
highest-value change in the plan.

**Files:**
- Modify: `backend/app/core/amazon_ads.py` (`list_ad_groups` lines 773-823; `list_targets` lines 826-933)
- Test: `backend/tests/core/test_amazon_ads_errors.py` (append)

**Interfaces:**
- Consumes: `PartialFetchError` from Task 2
- Produces: `list_ad_groups(access_token, profile_id) -> list[dict]` and
  `list_targets(access_token, profile_id) -> tuple[list[dict], bool, int, int]`
  — both raise `PartialFetchError` on any sub-fetch failure.
  **`list_targets` keeps its 4-tuple return** `(targets, was_truncated, total_pages, total_rows)`;
  `campaigns/service.py` unpacks all four. Do not change the arity.
  On failure, `PartialFetchError.items` holds the normalised target list only —
  callers that need the tuple treat a raised error as `was_truncated=True`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/core/test_amazon_ads_errors.py`:

```python
def test_list_ad_groups_raises_when_sp_fails(fake_requests):
    fake_requests.queue_response("POST", "/sp/adGroups/list", 502, {"code": "E", "details": "d"})
    fake_requests.queue_response("POST", "/sb/v4/adGroups/list", 200, {"adGroups": []})

    with pytest.raises(PartialFetchError):
        amazon_ads.list_ad_groups("tok", 123)


def test_list_targets_raises_and_keeps_partial_keywords(fake_requests):
    """The 215k-keyword-loss regression test.

    SP keywords dies on a dropped connection; SB keywords succeed. The caller
    must be told, and must still receive the SB rows.
    """
    from requests.exceptions import ConnectionError as ReqConnectionError

    fake_requests.queue_exception("POST", "/sp/keywords/list", ReqConnectionError("Remote end closed connection"))
    fake_requests.queue_response("POST", "/sp/targets/list", 200, {"targetingClauses": []})
    fake_requests.queue_response(
        "GET", "/sb/keywords", 200,
        [{"keywordId": "9001", "adGroupId": "500", "matchType": "EXACT",
          "keywordText": "mug", "bid": 1.0, "state": "ENABLED"}],
    )

    with pytest.raises(PartialFetchError) as excinfo:
        amazon_ads.list_targets("tok", 123)

    assert any("SP keywords" in f for f in excinfo.value.failures)
    assert len(excinfo.value.items) == 1
    assert excinfo.value.items[0]["amazon_target_id"] == 9001


def test_list_targets_succeeds_quietly_when_all_sources_ok(fake_requests):
    fake_requests.queue_response("POST", "/sp/keywords/list", 200, {"keywords": []})
    fake_requests.queue_response("POST", "/sp/targets/list", 200, {"targetingClauses": []})
    fake_requests.queue_response("GET", "/sb/keywords", 200, [])

    targets, truncated, pages, rows = amazon_ads.list_targets("tok", 123)

    assert targets == []
    assert truncated is False
    assert rows == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/core/test_amazon_ads_errors.py -q
```

Expected: the two new failure tests FAIL (no exception raised — the functions
currently return empty/partial lists silently).

- [ ] **Step 3: Apply the same pattern to `list_ad_groups`**

In `list_ad_groups`, replace each of the two `except AmazonApiError` /
`except Exception` pairs with a single accumulating handler, and add the raise
before `return ad_groups`:

```python
    failures: list[str] = []
```
declared next to `ad_groups: list[dict[str, Any]] = []`, then for each sub-fetch:

```python
    except Exception as exc:
        msg = f"SP ad groups fetch failed for profile {profile_id}: {exc}"
        logger.error("[amazon_ads] %s", msg)
        failures.append(msg)
```
(and the SB equivalent with `"SB ad groups"`), then before the return:

```python
    if failures:
        raise PartialFetchError(
            f"Ad group fetch incomplete for profile {profile_id}: " + "; ".join(failures),
            ad_groups,
            failures,
        )
    return ad_groups
```

- [ ] **Step 4: Apply the same pattern to `list_targets`**

`list_targets` has three sub-fetches (SP keywords, SP product targets, SB
keywords). Add `failures: list[str] = []` next to `targets: list[...] = []`,
replace all three `except` pairs with accumulating handlers using labels
`"SP keywords"`, `"SP product targets"`, `"SB keywords"`, and replace the
final return block:

```python
    total_rows = len(targets)
    logger.info(
        "[amazon_ads] list_targets COMPLETE profile=%s pages=%d rows=%d truncated=%s cap=%d failures=%d",
        profile_id, total_pages, total_rows, was_truncated, max_pages_cap, len(failures),
    )
    if failures:
        raise PartialFetchError(
            f"Target fetch incomplete for profile {profile_id}: " + "; ".join(failures),
            targets,
            failures,
        )
    return targets, was_truncated, total_pages, total_rows
```

- [ ] **Step 5: Run the full test file to verify it passes**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/core/test_amazon_ads_errors.py -q
```

Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/amazon_ads.py backend/tests/core/test_amazon_ads_errors.py
git commit -m "fix: list_ad_groups and list_targets raise on partial failure"
```

---

### Task 4: Service layer persists partial data and surfaces errors

The client now raises. Without this task, a `PartialFetchError` becomes an
HTTP 500 and the partial rows are discarded — worse than before. This task
makes the sync endpoints return `200` with an explicit `errors` array, and
critically **skip soft-delete** so incomplete data never deletes live rows.

**Files:**
- Modify: `backend/app/modules/campaigns/service.py` (`sync_campaigns` ~63-128, `sync_ad_groups` ~130-229, `sync_targets` ~231-320)
- Modify: `backend/app/modules/campaigns/schemas.py`
- Test: `backend/tests/modules/test_sync_partial.py` (create; add `backend/tests/modules/__init__.py`)

**Interfaces:**
- Consumes: `PartialFetchError` (Tasks 2-3)
- Produces: each `sync_*` method's returned dict gains `"errors": list[str]`
  and `"partial": bool`. Existing keys (`upserted`, `soft_deleted`, `skipped`)
  keep their names and meaning so the frontend does not break.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/modules/__init__.py` (empty) and
`backend/tests/modules/test_sync_partial.py`:

```python
"""A partial fetch must persist what succeeded, skip soft-delete, and report errors."""
import pytest

from app.core.amazon_ads import PartialFetchError


def test_partial_fetch_error_carries_items_and_failures():
    exc = PartialFetchError("boom", [{"amazon_campaign_id": 1}], ["SP campaigns failed"])

    assert exc.items == [{"amazon_campaign_id": 1}]
    assert exc.failures == ["SP campaigns failed"]
    assert "boom" in str(exc)


def test_soft_delete_must_be_skipped_on_partial_data():
    """Documents the invariant this task enforces.

    If Amazon returned an incomplete list, rows absent from it are NOT absent
    from Amazon — they were simply not fetched. Soft-deleting them destroys
    live data. sync_* must set partial=True and skip soft_delete_missing.
    """
    exc = PartialFetchError("incomplete", [], ["SP keywords failed"])

    assert exc.failures, "a partial fetch always records why"
```

- [ ] **Step 2: Run to verify collection works**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/modules/test_sync_partial.py -q
```

Expected: 2 passed. (These pin the contract; the behavioural change is
verified end-to-end in Task 7 against the live account, because
`sync_campaigns` needs a real DB session that unit tests here do not provide.)

- [ ] **Step 3: Update `sync_campaigns` in `campaigns/service.py`**

Find the existing fetch block (around line 74) which currently does
`except Exception as exc:` → `logger.error(...)` → `raise HTTPException(...)`.
Add a `PartialFetchError` handler *before* the generic one, and track state:

```python
        all_errors: list[str] = []
        partial = False
```
declared alongside the existing counters, then in the per-profile fetch:

```python
            except PartialFetchError as exc:
                # Persist what Amazon did return, but remember the view is incomplete.
                campaigns = exc.items
                all_errors.extend(exc.failures)
                partial = True
                logger.error("[svc] sync_campaigns PARTIAL for profile %s: %s", profile.id, exc)
            except Exception as exc:
                logger.error("Campaign fetch failed for profile %s: %s", profile.id, exc)
                raise HTTPException(status_code=502, detail=f"Campaign fetch failed: {exc}")
```

Then guard the soft-delete (existing condition around line 114) so it also
requires `not partial`:

```python
            if campaigns and not partial:
                # ... existing soft_delete_missing call unchanged ...
            elif partial:
                logger.warning(
                    "[svc] campaign soft_delete_missing SKIPPED profile=%s (partial fetch — %d errors)",
                    profile.id, len(all_errors),
                )
```

And extend the returned dict:

```python
        return {
            "upserted": total_upserted,
            "soft_deleted": total_deleted,
            "skipped": total_skipped,
            "errors": all_errors,
            "partial": partial,
        }
```

Add the import at the top of the file:

```python
from app.core.amazon_ads import PartialFetchError
```

- [ ] **Step 4: Apply the identical pattern to `sync_ad_groups` and `sync_targets`**

Same three changes in each: a `PartialFetchError` handler before the generic
`except`, `and not partial` added to the soft-delete condition, and
`"errors"` / `"partial"` added to the returned dict.

For `sync_targets`, the fetch unpacks a 4-tuple. On `PartialFetchError` there
is no tuple, so set the companions explicitly:

```python
            except PartialFetchError as exc:
                targets = exc.items
                was_truncated = True   # incomplete view — never soft-delete
                pages = 0
                rows = len(targets)
                all_errors.extend(exc.failures)
                partial = True
                logger.error("[svc] sync_targets PARTIAL for profile %s: %s", profile.id, exc)
```

- [ ] **Step 5: Add `errors` and `partial` to the response schemas**

In `backend/app/modules/campaigns/schemas.py`, add to whichever model the sync
endpoints return (the routers currently return raw `JSONResponse` dicts for
campaign/ad-group/target sync, so if no schema exists for them, no change is
needed here — verify with `grep -n "sync" backend/app/modules/campaigns/schemas.py`
and only add fields to models that exist).

- [ ] **Step 6: Restart the API and confirm it boots**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose restart api && sleep 12 && curl -s http://localhost:8000/health
```

Expected: `{"status":"ok",...}`. A traceback here means an import or syntax
error; fix before committing.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/campaigns/ backend/tests/modules/
git commit -m "fix: sync services persist partial data, skip soft-delete, return errors"
```

---

### Task 5: Retry with backoff on paginated fetches

This is what actually recovers the 215,000 keywords. A single dropped
connection part-way through ~230 sequential page requests currently discards
the entire fetch.

**Files:**
- Modify: `backend/app/core/amazon_ads.py` (`_post_list_paginated` lines 410-457, `_get_list_paginated_sb` lines 460-507)
- Modify: `backend/app/config.py`
- Test: `backend/tests/core/test_amazon_ads_retry.py`

**Interfaces:**
- Consumes: `fake_requests`, `no_sleep` fixtures from Task 1
- Produces: new settings `amazon_fetch_max_retries: int = 4` and
  `amazon_fetch_backoff_sec: float = 2.0`. Both paginated helpers keep their
  existing signatures and return types.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/core/test_amazon_ads_retry.py`:

```python
"""A transient connection error mid-pagination must be retried, not fatal."""
import pytest
from requests.exceptions import ConnectionError as ReqConnectionError

from app.core import amazon_ads
from app.core.amazon_ads import PartialFetchError


def test_transient_connection_error_is_retried_and_succeeds(fake_requests):
    """First attempt drops; retry succeeds. The fetch must complete normally."""
    fake_requests.queue_exception("POST", "/sp/campaigns/list", ReqConnectionError("Remote end closed"))
    fake_requests.queue_response(
        "POST", "/sp/campaigns/list", 200,
        {"campaigns": [{"campaignId": "5", "name": "C", "state": "ENABLED",
                        "budget": {"budget": 1.0}, "targetingType": "MANUAL"}]},
    )
    fake_requests.queue_response("POST", "/sb/v4/campaigns/list", 200, {"campaigns": []})

    result = amazon_ads.list_campaigns("tok", 123)

    assert len(result) == 1, "retry should have recovered the fetch"


def test_retries_are_bounded_then_raise(fake_requests):
    """Persistent failure must eventually give up — not loop forever."""
    for _ in range(10):
        fake_requests.queue_exception("POST", "/sp/campaigns/list", ReqConnectionError("down"))
    fake_requests.queue_response("POST", "/sb/v4/campaigns/list", 200, {"campaigns": []})

    with pytest.raises(PartialFetchError):
        amazon_ads.list_campaigns("tok", 123)

    sp_calls = [c for c in fake_requests.calls if "/sp/campaigns/list" in c[1]]
    assert 2 <= len(sp_calls) <= 6, f"expected bounded retries, saw {len(sp_calls)}"


def test_http_4xx_is_not_retried(fake_requests):
    """A 401/403 will never succeed on retry — fail fast, don't hammer Amazon."""
    fake_requests.queue_response("POST", "/sp/campaigns/list", 403, {"code": "FORBIDDEN", "details": "no"})
    fake_requests.queue_response("POST", "/sb/v4/campaigns/list", 200, {"campaigns": []})

    with pytest.raises(PartialFetchError):
        amazon_ads.list_campaigns("tok", 123)

    sp_calls = [c for c in fake_requests.calls if "/sp/campaigns/list" in c[1]]
    assert len(sp_calls) == 1, "4xx must not be retried"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/core/test_amazon_ads_retry.py -q
```

Expected: `test_transient_connection_error_is_retried_and_succeeds` FAILS —
currently one drop kills the whole fetch.

- [ ] **Step 3: Add the settings**

In `backend/app/config.py`, after `amazon_full_sync_max_pages`:

```python
    # Retry policy for paginated Amazon list fetches. A single dropped
    # connection part-way through ~230 sequential page requests used to
    # discard the entire fetch (observed: 215k keywords lost).
    amazon_fetch_max_retries: int = 4
    amazon_fetch_backoff_sec: float = 2.0
```

- [ ] **Step 4: Add the retry helper and use it in both paginated functions**

Add near the top of `amazon_ads.py`, after the module logger:

```python
import time

# Exceptions worth retrying: transport-level failures and Amazon 5xx/429.
_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """Issue a request, retrying transient failures with exponential backoff.

    Retries on transport errors and on HTTP 429/5xx. Does NOT retry 4xx other
    than 429 — those never succeed on retry and retrying just hammers Amazon.
    Raises the final exception, or returns the final response for the caller
    to run through _raise_for_amazon_error().
    """
    attempts = max(1, settings.amazon_fetch_max_retries)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < attempts:
                    delay = settings.amazon_fetch_backoff_sec * (2 ** (attempt - 1))
                    logger.warning(
                        "[amazon_ads] HTTP %d on %s — retry %d/%d in %.1fs",
                        resp.status_code, url, attempt, attempts, delay,
                    )
                    time.sleep(delay)
                    continue
            return resp
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if attempt < attempts:
                delay = settings.amazon_fetch_backoff_sec * (2 ** (attempt - 1))
                logger.warning(
                    "[amazon_ads] %s on %s — retry %d/%d in %.1fs",
                    type(exc).__name__, url, attempt, attempts, delay,
                )
                time.sleep(delay)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"_request_with_retry exhausted without result for {url}")
```

Then in `_post_list_paginated`, replace line 439:

```python
        resp = requests.post(url, json=body, headers=headers, timeout=30)
```
with:
```python
        resp = _request_with_retry("POST", url, json=body, headers=headers, timeout=30)
```

And in `_get_list_paginated_sb`, replace line 481:

```python
        resp = requests.get(url, params=params, headers=headers, timeout=30)
```
with:
```python
        resp = _request_with_retry("GET", url, params=params, headers=headers, timeout=30)
```

Note: the `fake_requests` fixture patches `requests.post`/`requests.get`, so
also patch `requests.request` in `conftest.py` — add to the fixture:

```python
    monkeypatch.setattr(
        amazon_ads.requests, "request",
        lambda method, url, **kw: fake._handle(method.upper(), url),
    )
```

- [ ] **Step 5: Run to verify all three pass**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/core/ -q
```

Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/amazon_ads.py backend/app/config.py backend/tests/
git commit -m "fix: retry paginated Amazon fetches on transient errors"
```

---

### Task 6: Configurable report poll ceiling

Measured: identical 2-day campaign reports took 23 min and 40 min on the same
day. Ad-group and keyword reports exceed the current 180-poll (~40 min real)
ceiling every time and have never once succeeded.

**Files:**
- Modify: `backend/app/core/amazon_reporting.py:76-77` and `_poll_report` lines 138-157
- Modify: `backend/app/config.py`
- Test: `backend/tests/core/test_amazon_reporting_poll.py`

**Interfaces:**
- Consumes: `fake_requests`, `no_sleep`
- Produces: settings `amazon_report_poll_max_attempts: int = 1440` and
  `amazon_report_poll_interval_sec: int = 10` (1440 × 10s = 4 hours).
  `_poll_report` keeps its signature.

**Note:** 4 hours only makes sense once sync runs in a background worker
(Plan 2). Until then a long-running HTTP request will still be abandoned by
the client — but the *server* will now finish the work and persist the rows,
which is strictly better than discarding them.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/core/test_amazon_reporting_poll.py`:

```python
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


def test_default_ceiling_allows_at_least_two_hours():
    """Regression guard: 180 polls (~40 min) was too short for real accounts."""
    total_seconds = (
        settings.amazon_report_poll_max_attempts * settings.amazon_report_poll_interval_sec
    )
    assert total_seconds >= 7200, f"ceiling is only {total_seconds}s — too short"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/core/test_amazon_reporting_poll.py -q
```

Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'amazon_report_poll_max_attempts'`.

- [ ] **Step 3: Add the settings**

In `backend/app/config.py`:

```python
    # Amazon report generation is queued on their side and highly variable —
    # measured 23 min and 40 min for the identical 2-day report on the same
    # day. The old hardcoded 180-poll (~40 min) ceiling meant ad-group and
    # keyword reports were abandoned every single time.
    amazon_report_poll_max_attempts: int = 1440   # 1440 x 10s = 4 hours
    amazon_report_poll_interval_sec: int = 10
```

- [ ] **Step 4: Use the settings in `_poll_report`**

Delete the module constants at lines 76-77 (`_POLL_MAX_ATTEMPTS`,
`_POLL_INTERVAL_SEC`) and read settings inside the function so tests can
monkeypatch them:

```python
def _poll_report(access_token: str, profile_id: int, report_id: str) -> dict[str, Any]:
    """Poll GET /reporting/reports/{id} until COMPLETED or failure."""
    url = f"{_REPORTING_BASE}/reporting/reports/{report_id}"
    poll_headers = {
        "Authorization": f"Bearer {access_token}",
        "Amazon-Advertising-API-ClientId": settings.amazon_client_id,
        "Amazon-Advertising-API-Scope": str(profile_id),
        "Accept": "application/vnd.createasyncreportrequest.v3+json",
    }
    max_attempts = settings.amazon_report_poll_max_attempts
    interval = settings.amazon_report_poll_interval_sec
    for attempt in range(1, max_attempts + 1):
        resp = requests.get(url, headers=poll_headers, timeout=30)
        _raise_for_amazon_error(resp)
        data = resp.json()
        status = data.get("status", "")
        # Log every 6th poll (once a minute at 10s) — 1440 lines per report is noise.
        if attempt == 1 or attempt % 6 == 0:
            logger.info("[reporting] Poll attempt %d/%d report %s status=%s",
                        attempt, max_attempts, report_id, status)
        if status == "COMPLETED":
            logger.info("[reporting] Report %s COMPLETED after %d polls", report_id, attempt)
            return data
        if status in ("FAILURE", "CANCELLED"):
            raise AmazonApiError(
                f"Report {report_id} ended with status {status}: {data.get('statusDetails', '')}"
            )
        time.sleep(interval)
    raise RuntimeError(
        f"Report {report_id} did not complete after {max_attempts} polls "
        f"({max_attempts * interval}s)"
    )
```

Then `grep -n "_POLL_MAX_ATTEMPTS\|_POLL_INTERVAL_SEC" backend/app/core/amazon_reporting.py`
and fix any remaining references.

- [ ] **Step 5: Run the whole suite**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests -q
```

Expected: 13 passed.

- [ ] **Step 6: Restart and confirm the API boots**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose restart api && sleep 12 && curl -s http://localhost:8000/health
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/amazon_reporting.py backend/app/config.py backend/tests/
git commit -m "fix: make report poll ceiling configurable, default 4 hours"
```

---

### Task 7: End-to-end verification against the live account

Unit tests prove the logic. This proves the bugs are actually dead against
real Amazon data. Account `85e0e890-6baf-45ef-b8de-026c07f050e0`, US profile
`89389798686160`.

**Files:**
- Create: `docs/superpowers/plans/2026-08-05-verification-results.md`

**Interfaces:**
- Consumes: everything above
- Produces: a written record of measured before/after numbers

- [ ] **Step 1: Capture the baseline**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T postgres psql -U ppc_os -d ppc_os -c "SELECT (SELECT count(*) FROM campaigns) camp,(SELECT count(*) FROM ad_groups) ag,(SELECT count(*) FROM targets) tgt,(SELECT count(*) FROM campaign_performance_daily) cperf,(SELECT count(*) FROM ad_group_performance_daily) agperf,(SELECT count(*) FROM target_performance_daily) tperf;"
```

Record the numbers. Expected before this plan: `267 | 1385 | 16680 | 10 | 0 | 0`.

- [ ] **Step 2: Re-run the targets sync and confirm the keyword count recovers**

The success criterion: **targets should approach ~232,000**, not 16,680. If
the SP keywords fetch drops a connection, the retry should now recover it.

```bash
cd /Users/tsth/Downloads/helium/ppc-os && TOKEN=$(ADMIN_EMAIL=$(grep -E '^SEED_ADMIN_EMAIL=' .env | cut -d= -f2-); ADMIN_PW=$(grep -E '^SEED_ADMIN_PASSWORD=' .env | cut -d= -f2-); curl -s -X POST http://localhost:8000/auth/login -H 'Content-Type: application/json' -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PW\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])") && curl -s -X POST "http://localhost:8000/accounts/85e0e890-6baf-45ef-b8de-026c07f050e0/targets/sync" -H "Authorization: Bearer $TOKEN"
```

Expected: response includes an `errors` array (empty on full success), and
`upserted` well above 16,680.

- [ ] **Step 3: Confirm a failing profile now reports its error**

The CA profile `1043372500031905` returns HTTP 502 from Amazon. Before this
plan it produced `"Campaign sync complete"` with 0 campaigns. Now it must
appear in `errors`.

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose logs api --since 10m 2>&1 | grep -iE "PARTIAL|failures=|soft_delete_missing SKIPPED"
```

Expected: at least one `PARTIAL` line naming profile `1043372500031905`, and a
`soft_delete_missing SKIPPED` confirming no destructive delete ran on
incomplete data.

- [ ] **Step 4: Re-run a short performance sync and confirm all three levels populate**

Use 2 days so the reports are as small as possible. The poll ceiling is now 4
hours, so ad-group and keyword reports should complete rather than being
abandoned.

```bash
cd /Users/tsth/Downloads/helium/ppc-os && TOKEN=$(ADMIN_EMAIL=$(grep -E '^SEED_ADMIN_EMAIL=' .env | cut -d= -f2-); ADMIN_PW=$(grep -E '^SEED_ADMIN_PASSWORD=' .env | cut -d= -f2-); curl -s -X POST http://localhost:8000/auth/login -H 'Content-Type: application/json' -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PW\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])") && curl -s --max-time 18000 -X POST "http://localhost:8000/performance/sync?account_id=85e0e890-6baf-45ef-b8de-026c07f050e0&days=2" -H "Authorization: Bearer $TOKEN"
```

Expected: `ad_group_rows > 0` and `target_rows > 0` — the numbers that have
**never** been non-zero. This is the headline result of the whole plan.

- [ ] **Step 5: Write up the results**

Create `docs/superpowers/plans/2026-08-05-verification-results.md` with a
before/after table for all six counts, the observed report durations, and any
errors that surfaced. This is the artefact to hand to the team.

- [ ] **Step 6: Commit**

```bash
git add docs/
git commit -m "docs: record end-to-end verification results"
```

---

## Self-Review

**Spec coverage.** Phase 0 (make failures visible) → Tasks 2, 3, 4. Phase 1
(stop losing data) → Tasks 5, 6. Prerequisites → Task 1. Proof → Task 7.
Bugs 2, 3, 4 and 8 from the diagnosis are all addressed. Bugs 5, 6, 7
(background worker, job state, scheduler) are explicitly deferred to Plan 2 —
that is a scope decision, not a gap.

**Placeholders.** No TBDs. Every code step contains real code. Task 4 Step 5
is conditional on what exists in `schemas.py`, with a `grep` given to
determine it — that is a verification instruction, not a placeholder.

**Type consistency.** `PartialFetchError(message: str, items: list[dict], failures: list[str])`
is defined in Task 2 and used with the same signature in Tasks 3, 4 and 5.
`list_targets` keeps its 4-tuple return throughout. Settings names
(`amazon_fetch_max_retries`, `amazon_fetch_backoff_sec`,
`amazon_report_poll_max_attempts`, `amazon_report_poll_interval_sec`) are
spelled identically in `config.py`, the implementations and the tests.

**Known limitation.** The 4-hour poll ceiling is only fully useful once Plan 2
lands. Until then the HTTP client still disconnects, though the server now
completes the work and persists the rows. This is called out in Task 6.

## Follow-up: Plan 2 (not yet written)

To be written after this plan lands:

- Background worker (Redis + ARQ or Celery), replacing the `threading.Thread` in `campaigns/router.py:397`
- Wire the existing unused `sync_jobs` table; delete the in-memory `_sync_jobs` dict
- Frontend polls job status instead of holding an HTTP request open
- Scheduler for periodic syncs
- Pre-VPS hardening: rotate secrets, bind ports to `127.0.0.1`, change `ChangeMe123!`, production build for the frontend container
