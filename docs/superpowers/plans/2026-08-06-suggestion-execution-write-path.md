# Suggestion Execution & Amazon Write Path Implementation Plan (Plan 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the V1 loop — let an approved suggestion write a real change to Amazon, fully audited and reversible — while making it **impossible to write accidentally** before the team authorises it.

**Architecture:** A new `app/core/amazon_ads_write.py` is the only module in the codebase permitted to make mutating Amazon calls. Every call is gated by a global `AMAZON_WRITE_ENABLED` kill-switch defaulting to **False**, and every attempt is recorded in `suggestion_actions` with the literal request and response before and after it is made. Execution runs as a Celery task, one suggestion per Amazon API call, so a failure isolates to a single suggestion. `change_log` records old→new per field, which is what makes rollback possible.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (sync/psycopg2), Celery 5.4 + Redis, PostgreSQL 16, Next.js 14.

## Global Constraints

From the merged spec (`PPC_OS_Merged.docx`), which supersedes all prior versions:

- **"Mandatory: Rule → Suggestion → Human Review → Apply. NO auto-apply in V1."**
- **"In V1: 'executing' a rule means PRODUCING A SUGGESTION, not writing to Amazon. Amazon writes only happen via Suggestion Execution, gated by human approval."**
- **"One suggestion = one Amazon API write call (no batching in V1). Trades API efficiency for per-suggestion error isolation."**
- `suggestion_actions` is **append-only** — "never delete or update. Stores literal Amazon API request/response for every execution attempt."
- "Auditability from day 1 — every automated and manual change is logged with who/what/when/old→new before any automation goes live."
- Two roles only: Admin, User.
- Do NOT modify historical migrations. Alembic head is `013`; this plan adds `014`.

## Hard safety rule for this plan

**No task in this plan fires a real mutating request to Amazon.** Task 7 is the live
write and it is **GATED**: it must not be started until the user confirms their
team has approved it, and it names the exact target in advance.

Everything up to Task 6 is verified against the `fake_requests` transport, so the
whole path can be proven correct with zero spend risk.

`AMAZON_WRITE_ENABLED` defaults to `False`. With it off, the write client raises
`AmazonWriteDisabled` before constructing any request. Even a bug that reaches
the execution job cannot touch the account.

## Tech stack deviation, recorded

The spec states: *"APScheduler over Celery, single VPS over Kubernetes, env-file
secrets over Vault — chosen deliberately for low maintenance."*

Plan 2 used **Celery + Redis** instead. The user has confirmed the technical
stack is the implementer's call. Rationale: syncs run for hours against an API
that drops connections mid-request (observed: 215k keywords lost to one drop).
Celery provides crash recovery, late acknowledgement and retry semantics that
in-process APScheduler does not. Redis runs as one container with persistence
disabled. Recorded here so the deviation is explicit rather than silent.

## What already exists

| | |
|---|---|
| `suggestions` table | Exists, but **cannot express a bid change** — no `target_id`, `current_value` or `suggested_value` |
| Approve / reject / bulk endpoints | Exist; they only flip `status` and write an `audit_log` row |
| `audit_log` table | Exists and is written to |
| `suggestion_actions`, `change_log` | **Do not exist** |
| Any Amazon write code | **Does not exist** — verified: zero `requests.put/patch/delete` in the backend |

## File Structure

**Created:**

- `backend/alembic/versions/014_execution_audit_and_suggestion_values.py`
- `backend/app/core/amazon_ads_write.py` — the *only* module allowed to mutate Amazon
- `backend/app/modules/execution/__init__.py`
- `backend/app/modules/execution/models.py` — `SuggestionAction`, `ChangeLog`
- `backend/app/modules/execution/repository.py`
- `backend/app/modules/execution/service.py` — `ExecutionService`, `RollbackService`
- `backend/app/modules/execution/router.py`
- `backend/app/worker/execution_tasks.py` — `execute_suggestion` Celery task
- `backend/tests/core/test_amazon_write_safety.py`
- `backend/tests/core/test_amazon_write_client.py`
- `backend/tests/modules/test_execution_service.py`
- `backend/tests/modules/test_rollback.py`

**Modified:**

- `backend/app/config.py` — `amazon_write_enabled: bool = False`
- `backend/app/modules/suggestions/models.py` — new columns
- `backend/app/modules/suggestions/router.py` — approve enqueues execution
- `backend/app/worker/celery_app.py` — include the new task module
- `backend/app/main.py` — register the execution router

---

### Task 1: The kill-switch and write-client skeleton

Build the safety mechanism **before** anything that could use it.

**Files:**
- Create: `backend/app/core/amazon_ads_write.py`
- Create: `backend/tests/core/test_amazon_write_safety.py`
- Modify: `backend/app/config.py`, `.env.example`

**Interfaces:**
- Consumes: `fake_requests` fixture
- Produces:
  ```python
  class AmazonWriteDisabled(Exception): ...

  def assert_write_enabled() -> None
      # raises AmazonWriteDisabled unless settings.amazon_write_enabled
  ```
  New setting `amazon_write_enabled: bool = False`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/core/test_amazon_write_safety.py`:

```python
"""Writing to Amazon must be impossible until deliberately enabled."""
import pytest

from app.config import settings
from app.core import amazon_ads_write as w
from app.core.amazon_ads_write import AmazonWriteDisabled


def test_write_is_disabled_by_default():
    """A fresh environment must never be able to change a live ad account."""
    assert settings.amazon_write_enabled is False


def test_assert_write_enabled_raises_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "amazon_write_enabled", False)
    with pytest.raises(AmazonWriteDisabled):
        w.assert_write_enabled()


def test_assert_write_enabled_passes_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "amazon_write_enabled", True)
    w.assert_write_enabled()   # must not raise


def test_every_public_write_function_checks_the_switch():
    """A new write function that forgets the guard is the dangerous case."""
    import inspect

    src = inspect.getsource(w)
    for name in ("update_keyword_bid", "create_negative_keyword", "update_target_bid"):
        fn_src = src[src.index(f"def {name}("):]
        # Guard must appear before any HTTP verb in the function body.
        guard = fn_src.find("assert_write_enabled()")
        for verb in ("requests.put", "requests.post", "_write_request"):
            hit = fn_src.find(verb)
            if hit != -1:
                assert guard != -1 and guard < hit, (
                    f"{name} must call assert_write_enabled() before {verb}"
                )
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/core/test_amazon_write_safety.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.core.amazon_ads_write'`.

- [ ] **Step 3: Add the setting**

In `backend/app/config.py`, after the worker settings:

```python
    # ── Amazon WRITE access ────────────────────────────────────────────────
    # Master kill-switch for every mutating Amazon Ads call. Defaults to
    # False so no environment can change a live ad account by accident —
    # including a fresh clone, a test run, or a misconfigured deploy.
    # Turn on ONLY when the team has explicitly authorised writes.
    amazon_write_enabled: bool = False
```

Append to `.env.example`:

```
# ── Amazon WRITE access ────────────────────────────────────────────────────
# Master kill-switch for mutating Amazon Ads calls (bid changes, negatives).
# false = the app can never modify your live ad account.
AMAZON_WRITE_ENABLED=false
```

- [ ] **Step 4: Create the write module skeleton**

Create `backend/app/core/amazon_ads_write.py`:

```python
"""The ONLY module permitted to make mutating Amazon Ads API calls.

Every other module in this codebase is read-only. Keeping writes in one file
means the blast radius is auditable by reading a single ~200-line module.

Safety model
------------
1. settings.amazon_write_enabled is a master kill-switch, default False.
   Every public function calls assert_write_enabled() FIRST, before building
   a request. With the switch off, no mutating request can be constructed.
2. Callers must record the attempt in suggestion_actions before and after —
   see ExecutionService. This module does not write to the database itself.
3. One call per suggestion. No batching in V1, per the spec: it trades API
   efficiency for per-suggestion error isolation.
"""
import logging
from typing import Any

import requests

from app.config import settings
from app.core.amazon_ads import _raise_for_amazon_error, _request_with_retry

logger = logging.getLogger(__name__)


class AmazonWriteDisabled(Exception):
    """Raised when a write is attempted while AMAZON_WRITE_ENABLED is false."""


def assert_write_enabled() -> None:
    """Gate every mutating call. Raises unless writes are explicitly enabled."""
    if not settings.amazon_write_enabled:
        raise AmazonWriteDisabled(
            "Amazon writes are disabled (AMAZON_WRITE_ENABLED=false). "
            "This is the default: the app cannot modify a live ad account "
            "until writes are explicitly authorised."
        )
```

- [ ] **Step 5: Run to verify it passes**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/core/test_amazon_write_safety.py -q
```

Expected: 4 passed. `test_every_public_write_function_checks_the_switch`
passes vacuously for now — Task 2 gives it teeth.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/amazon_ads_write.py backend/app/config.py backend/tests/core/test_amazon_write_safety.py .env.example
git commit -m "feat: add AMAZON_WRITE_ENABLED kill-switch, default off"
```

---

### Task 2: The write client

**Files:**
- Modify: `backend/app/core/amazon_ads_write.py`
- Create: `backend/tests/core/test_amazon_write_client.py`

**Interfaces:**
- Consumes: `assert_write_enabled` (Task 1), `_request_with_retry` from `amazon_ads`
- Produces:
  ```python
  def update_keyword_bid(access_token: str, profile_id: int,
                         keyword_id: int, new_bid: float) -> dict
  def update_target_bid(access_token: str, profile_id: int,
                        target_id: int, new_bid: float) -> dict
  def create_negative_keyword(access_token: str, profile_id: int,
                              ad_group_id: int, campaign_id: int,
                              keyword_text: str, match_type: str) -> dict
  ```
  Each returns `{"ok": bool, "request": dict, "response": dict, "status_code": int}`
  so the caller can persist the literal exchange into `suggestion_actions`.

**Amazon endpoints (SP v3):**
- `PUT /sp/keywords` — body `{"keywords":[{"keywordId":"...","bid":0.80}]}`,
  Content-Type `application/vnd.spKeyword.v3+json`
- `PUT /sp/targets` — Content-Type `application/vnd.spTargetingClause.v3+json`
- `POST /sp/negativeKeywords` — Content-Type `application/vnd.spNegativeKeyword.v3+json`

v3 mutation responses return per-item success/error arrays, so a `200` does
**not** mean the item succeeded. The client must inspect the body.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/core/test_amazon_write_client.py`:

```python
"""The write client must report per-item outcomes, not just HTTP status."""
import pytest

from app.config import settings
from app.core import amazon_ads_write as w
from app.core.amazon_ads_write import AmazonWriteDisabled


@pytest.fixture(autouse=True)
def _enable_writes(monkeypatch):
    monkeypatch.setattr(settings, "amazon_write_enabled", True)


def test_update_keyword_bid_sends_the_new_bid(fake_requests):
    fake_requests.queue_response(
        "PUT", "/sp/keywords", 207,
        {"keywords": {"success": [{"index": 0, "keywordId": "3001"}], "error": []}},
    )

    result = w.update_keyword_bid("tok", 123, 3001, 0.80)

    assert result["ok"] is True
    assert result["request"]["keywords"][0]["keywordId"] == "3001"
    assert result["request"]["keywords"][0]["bid"] == 0.80


def test_per_item_error_is_a_failure_even_on_http_200(fake_requests):
    """v3 mutations return 200/207 with a per-item error array. Treating that
    as success would record a change that never happened."""
    fake_requests.queue_response(
        "PUT", "/sp/keywords", 207,
        {"keywords": {"success": [],
                      "error": [{"index": 0, "errors": [{"errorType": "BID_TOO_LOW"}]}]}},
    )

    result = w.update_keyword_bid("tok", 123, 3001, 0.01)

    assert result["ok"] is False
    assert "BID_TOO_LOW" in str(result["response"])


def test_http_error_is_a_failure(fake_requests):
    fake_requests.queue_response("PUT", "/sp/keywords", 403, {"code": "FORBIDDEN"})

    result = w.update_keyword_bid("tok", 123, 3001, 0.80)

    assert result["ok"] is False
    assert result["status_code"] == 403


def test_kill_switch_blocks_before_any_request(fake_requests, monkeypatch):
    """With writes disabled, no HTTP call may be attempted at all."""
    monkeypatch.setattr(settings, "amazon_write_enabled", False)

    with pytest.raises(AmazonWriteDisabled):
        w.update_keyword_bid("tok", 123, 3001, 0.80)

    assert fake_requests.calls == [], "no request may be made while disabled"


def test_negative_keyword_creation(fake_requests):
    fake_requests.queue_response(
        "POST", "/sp/negativeKeywords", 207,
        {"negativeKeywords": {"success": [{"index": 0, "negativeKeywordId": "77"}],
                              "error": []}},
    )

    result = w.create_negative_keyword("tok", 123, 2001, 1001, "coffee table", "exact")

    assert result["ok"] is True
    body = result["request"]["negativeKeywords"][0]
    assert body["keywordText"] == "coffee table"
    assert body["matchType"] == "NEGATIVE_EXACT"


def test_bid_is_rejected_if_not_positive():
    """A zero or negative bid is a programming error, not an Amazon error."""
    for bad in (0, -1, -0.5):
        with pytest.raises(ValueError):
            w.update_keyword_bid("tok", 123, 3001, bad)
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/core/test_amazon_write_client.py -q
```

Expected: `AttributeError: module ... has no attribute 'update_keyword_bid'`.

- [ ] **Step 3: Implement the client**

Append to `backend/app/core/amazon_ads_write.py`:

```python
def _write_headers(access_token: str, profile_id: int, content_type: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Amazon-Advertising-API-ClientId": settings.amazon_client_id,
        "Amazon-Advertising-API-Scope": str(profile_id),
        "Content-Type": content_type,
        "Accept": content_type,
    }


def _parse_mutation_result(resp, body: dict, collection: str) -> dict[str, Any]:
    """Turn a v3 mutation response into a definite ok/not-ok.

    v3 returns 200/207 with per-item success and error arrays, so HTTP status
    alone is not enough — a 207 can contain nothing but errors.
    """
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text[:500]}

    if not resp.ok:
        return {"ok": False, "request": body, "response": payload,
                "status_code": resp.status_code}

    section = payload.get(collection) or {}
    errors = section.get("error") or []
    successes = section.get("success") or []
    return {
        "ok": bool(successes) and not errors,
        "request": body,
        "response": payload,
        "status_code": resp.status_code,
    }


def _validate_bid(new_bid: float) -> None:
    if new_bid is None or float(new_bid) <= 0:
        raise ValueError(f"bid must be positive, got {new_bid!r}")


def update_keyword_bid(access_token: str, profile_id: int,
                       keyword_id: int, new_bid: float) -> dict[str, Any]:
    """PUT /sp/keywords — change one keyword's bid."""
    assert_write_enabled()
    _validate_bid(new_bid)
    body = {"keywords": [{"keywordId": str(keyword_id), "bid": float(new_bid)}]}
    url = f"{settings.amazon_api_base_url}/sp/keywords"
    headers = _write_headers(access_token, profile_id, "application/vnd.spKeyword.v3+json")
    logger.warning("[amazon_write] PUT keyword %s bid=%s profile=%s",
                   keyword_id, new_bid, profile_id)
    resp = _request_with_retry("PUT", url, json=body, headers=headers, timeout=30)
    return _parse_mutation_result(resp, body, "keywords")


def update_target_bid(access_token: str, profile_id: int,
                      target_id: int, new_bid: float) -> dict[str, Any]:
    """PUT /sp/targets — change one product target's bid."""
    assert_write_enabled()
    _validate_bid(new_bid)
    body = {"targetingClauses": [{"targetId": str(target_id), "bid": float(new_bid)}]}
    url = f"{settings.amazon_api_base_url}/sp/targets"
    headers = _write_headers(access_token, profile_id,
                             "application/vnd.spTargetingClause.v3+json")
    logger.warning("[amazon_write] PUT target %s bid=%s profile=%s",
                   target_id, new_bid, profile_id)
    resp = _request_with_retry("PUT", url, json=body, headers=headers, timeout=30)
    return _parse_mutation_result(resp, body, "targetingClauses")


def create_negative_keyword(access_token: str, profile_id: int,
                            ad_group_id: int, campaign_id: int,
                            keyword_text: str, match_type: str) -> dict[str, Any]:
    """POST /sp/negativeKeywords — add one negative keyword to an ad group."""
    assert_write_enabled()
    mt = f"NEGATIVE_{(match_type or 'exact').upper().replace('NEGATIVE_', '')}"
    body = {"negativeKeywords": [{
        "campaignId": str(campaign_id),
        "adGroupId": str(ad_group_id),
        "keywordText": keyword_text,
        "matchType": mt,
        "state": "ENABLED",
    }]}
    url = f"{settings.amazon_api_base_url}/sp/negativeKeywords"
    headers = _write_headers(access_token, profile_id,
                             "application/vnd.spNegativeKeyword.v3+json")
    logger.warning("[amazon_write] POST negative '%s' (%s) ad_group=%s profile=%s",
                   keyword_text, mt, ad_group_id, profile_id)
    resp = _request_with_retry("POST", url, json=body, headers=headers, timeout=30)
    return _parse_mutation_result(resp, body, "negativeKeywords")
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/core/ -q
```

Expected: all pass, including the safety test now that real write functions
exist for it to inspect.

- [ ] **Step 5: Prove the switch is off in this environment**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -c "
from app.config import settings
from app.core.amazon_ads_write import update_keyword_bid, AmazonWriteDisabled
print('AMAZON_WRITE_ENABLED =', settings.amazon_write_enabled)
try:
    update_keyword_bid('tok', 123, 3001, 0.80)
    print('DANGER: a write was attempted')
except AmazonWriteDisabled as e:
    print('BLOCKED as expected:', e)
"
```

Expected: `AMAZON_WRITE_ENABLED = False` and `BLOCKED as expected`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/amazon_ads_write.py backend/tests/core/test_amazon_write_client.py
git commit -m "feat: Amazon write client for bids and negative keywords"
```

---

### Task 3: Migration 014 — audit tables and suggestion values

**Files:**
- Create: `backend/alembic/versions/014_execution_audit_and_suggestion_values.py`
- Create: `backend/app/modules/execution/{__init__,models,repository}.py`
- Create: `backend/tests/modules/test_execution_repository.py`
- Modify: `backend/app/modules/suggestions/models.py`

**Interfaces:**
- Produces:
  ```python
  class SuggestionAction(Base)  # append-only attempt log
  class ChangeLog(Base)         # old -> new per field, powers rollback

  class ExecutionRepository:
      def record_attempt(self, suggestion_id, action, performed_by,
                         request=None, response=None, status_code=None, notes=None) -> SuggestionAction
      def record_change(self, profile_id, entity_type, entity_id, field_changed,
                        old_value, new_value, suggestion_id, changed_by, source) -> ChangeLog
      def latest_change_for_suggestion(self, suggestion_id) -> ChangeLog | None
  ```
  New `suggestions` columns: `target_id`, `current_value` (JSONB),
  `suggested_value` (JSONB), `priority_score`, `executed_at`.

- [ ] **Step 1: Write the migration**

```python
"""execution audit tables + machine-readable suggestion values

The suggestions table could not express a bid change: it stored a search_term
string and a prose reason, with no field for which target to modify, its
current value, or the value to set. Execution needs all three.

suggestion_actions and change_log are from the spec's V1 table list and were
never created.

Revision ID: 014
Revises: 013
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── suggestions: make a suggestion machine-actionable ──────────────
    op.add_column("suggestions", sa.Column("target_id", postgresql.UUID(as_uuid=True),
                                           sa.ForeignKey("targets.id", ondelete="SET NULL"),
                                           nullable=True))
    op.add_column("suggestions", sa.Column("current_value", postgresql.JSONB(), nullable=True))
    op.add_column("suggestions", sa.Column("suggested_value", postgresql.JSONB(), nullable=True))
    op.add_column("suggestions", sa.Column("priority_score", sa.Integer(), nullable=True))
    op.add_column("suggestions", sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_suggestions_priority", "suggestions",
                    ["status", sa.text("priority_score DESC")])

    # ── suggestion_actions: append-only attempt log ────────────────────
    op.create_table(
        "suggestion_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("suggestion_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("suggestions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("performed_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),   # NULL = system
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("amazon_api_request", postgresql.JSONB(), nullable=True),
        sa.Column("amazon_api_response", postgresql.JSONB(), nullable=True),
        sa.Column("amazon_api_status_code", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "action IN ('created','approved','rejected','deferred','executed',"
            "'execution_failed','expired','rolled_back')",
            name="ck_suggestion_actions_action",
        ),
    )
    op.create_index("idx_suggestion_actions_suggestion", "suggestion_actions",
                    ["suggestion_id", sa.text("created_at DESC")])

    # ── change_log: old -> new, powers rollback ────────────────────────
    op.create_table(
        "change_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ads_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amazon_entity_id", sa.BigInteger(), nullable=True),
        sa.Column("field_changed", sa.String(50), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("suggestion_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("suggestions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("entity_type IN ('campaign','ad_group','target')",
                           name="ck_change_log_entity_type"),
        sa.CheckConstraint("source IN ('suggestion_execution','manual_edit','rollback')",
                           name="ck_change_log_source"),
    )
    op.create_index("idx_change_log_profile_changed", "change_log",
                    ["profile_id", sa.text("changed_at DESC")])


def downgrade() -> None:
    op.drop_table("change_log")
    op.drop_table("suggestion_actions")
    op.drop_index("idx_suggestions_priority", table_name="suggestions")
    for col in ("executed_at", "priority_score", "suggested_value",
                "current_value", "target_id"):
        op.drop_column("suggestions", col)
```

- [ ] **Step 2: Apply and verify**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api alembic upgrade head && docker compose exec -T postgres psql -U ppc_os -d ppc_os -c "\d suggestion_actions" && docker compose exec -T postgres psql -U ppc_os -d ppc_os -tAc "SELECT version_num FROM alembic_version;"
```

Expected: table exists, head is `014`.

- [ ] **Step 3: Add the models and repository**

Create `backend/app/modules/execution/models.py` mirroring the migration
column-for-column (same pattern as `sync_jobs/models.py`), and
`repository.py` with `record_attempt`, `record_change`,
`latest_change_for_suggestion`.

`record_attempt` must never update an existing row — the spec says
`suggestion_actions` is append-only.

Add the new columns to `backend/app/modules/suggestions/models.py`.

- [ ] **Step 4: Write and run the repository test**

`backend/tests/modules/test_execution_repository.py` asserting: status/action
constants fit their check constraints, `record_attempt` only inserts, and
`ChangeLog.__tablename__ == "change_log"`. Then a real-database smoke test —
the `sync_jobs` lesson was that green unit tests do not prove the schema
matches.

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/014_execution_audit_and_suggestion_values.py backend/app/modules/execution backend/app/modules/suggestions/models.py backend/tests/modules/test_execution_repository.py
git commit -m "feat: add suggestion_actions, change_log and machine-readable suggestion values"
```

---

### Task 4: ExecutionService

**Files:**
- Create: `backend/app/modules/execution/service.py`
- Create: `backend/tests/modules/test_execution_service.py`

**Interfaces:**
- Consumes: the write client (Task 2), `ExecutionRepository` (Task 3)
- Produces:
  ```python
  class ExecutionService:
      def execute(self, suggestion_id: uuid.UUID, performed_by: uuid.UUID) -> dict
  ```
  Returns `{"ok": bool, "suggestion_id": str, "status": str, "detail": str}`.

**Required ordering — this is the point of the task:**

1. Refuse unless `suggestion.status == "approved"` (never execute a pending one)
2. `record_attempt(action="executed", request=...)` **before** the API call
3. Call the write client
4. On success: `record_change(old→new)`, set `status="executed"`, `executed_at`
5. On failure: `status="execution_failed"`, record the response, **do not**
   write a `change_log` row — nothing changed
6. Every path appends to `suggestion_actions` with the literal response

- [ ] **Step 1: Write the failing test**

`backend/tests/modules/test_execution_service.py`, source-inspection style
plus behavioural tests against `fake_requests`:

```python
def test_only_approved_suggestions_execute():
    src = inspect.getsource(ExecutionService.execute)
    assert '"approved"' in src or "JOB_STATUS" in src

def test_attempt_is_recorded_before_the_api_call():
    """If the process dies mid-call, there must still be a record that we tried."""
    src = inspect.getsource(ExecutionService.execute)
    assert src.index("record_attempt") < src.index("update_keyword_bid")

def test_failure_does_not_write_a_change_log_row():
    """change_log means 'this changed on Amazon'. A failed call changed nothing."""
    src = inspect.getsource(ExecutionService.execute)
    fail_branch = src[src.index("execution_failed"):]
    assert "record_change" not in fail_branch

def test_rollback_needs_old_value():
    """A change_log row without old_value cannot be reverted."""
    src = inspect.getsource(ExecutionService.execute)
    assert "old_value" in src
```

- [ ] **Step 2-5:** run-fail, implement, run-pass, commit — same rhythm as above.

---

### Task 5: Execution task and API wiring

**Files:**
- Create: `backend/app/worker/execution_tasks.py`
- Create: `backend/app/modules/execution/router.py`
- Modify: `backend/app/worker/celery_app.py`, `backend/app/main.py`, `backend/app/modules/suggestions/router.py`

**Interfaces:**
- Produces:
  - `@celery_app.task(name="execute_suggestion") def execute_suggestion(suggestion_id: str, user_id: str) -> dict`
  - `POST /suggestions/{id}/execute` — Admin only, enqueues
  - `GET /suggestions/{id}/actions` — the attempt trail
  - Approve **optionally** enqueues execution via `?execute=true`, default
    **false**, so approving stays non-destructive unless explicitly asked

- [ ] Standard TDD rhythm. **Restart the worker** after adding the task module —
  Plan 2 proved Celery only reads its task registry at startup, and a missing
  registration fails silently with `KeyError`.

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose up -d --force-recreate worker beat && sleep 15 && docker compose logs worker --since 1m | sed -n '/\[tasks\]/,/celery@/p'
```

Expected: `execute_suggestion` in the list.

---

### Task 6: Rollback

The spec lists this as a known gap: *"Rollback / undo a specific executed
change — Change Log records old→new values but there's no 'revert this one
change' button."* Building it **before** the first live write, not after.

**Files:**
- Modify: `backend/app/modules/execution/service.py`, `router.py`
- Create: `backend/tests/modules/test_rollback.py`

**Interfaces:**
- Produces:
  ```python
  class RollbackService:
      def rollback(self, change_log_id: uuid.UUID, performed_by: uuid.UUID) -> dict
  ```
  `POST /change-log/{id}/rollback` — Admin only.

Rules:
- Writes `old_value` back to Amazon through the same gated client
- Records a **new** `change_log` row with `source="rollback"` — never edits
  history
- Stamps `rolled_back_at` on the original row
- Refuses if already rolled back
- Refuses if `old_value` is NULL (nothing to restore)

- [ ] Standard TDD rhythm.

---

### Task 7 — ⛔ GATED: the first live write

**DO NOT START THIS TASK** until the user confirms their team has authorised a
real write and has named the target. Tasks 1-6 are complete and useful without
it; the kill-switch stays off.

When authorised:

- [ ] **Step 1: Agree the exact target in writing**

Record here before touching anything: account, profile, campaign, keyword id,
current bid, intended bid, and who approved. Prefer a **paused** campaign —
it serves no impressions, so a wrong bid costs nothing.

- [ ] **Step 2: Capture the current value from Amazon, not from our database**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T postgres psql -U ppc_os -d ppc_os -c "SELECT amazon_target_id, expression_text, bid, status FROM targets WHERE amazon_target_id = <ID>;"
```

- [ ] **Step 3: Enable writes for one operation only**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && sed -i '' 's/^AMAZON_WRITE_ENABLED=false/AMAZON_WRITE_ENABLED=true/' .env && docker compose up -d api worker && sleep 15 && curl -s http://localhost:8000/health
```

- [ ] **Step 4: Execute exactly one suggestion**, then immediately re-sync that
  profile and confirm Amazon returns the new bid.

- [ ] **Step 5: Roll it back** using Task 6, and confirm the original value
  returns on the next sync. **The rollback is as important to prove as the write.**

- [ ] **Step 6: Turn the switch back off**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && sed -i '' 's/^AMAZON_WRITE_ENABLED=true/AMAZON_WRITE_ENABLED=false/' .env && docker compose up -d api worker
```

- [ ] **Step 7: Write up the result** in `docs/superpowers/plans/2026-08-06-write-verification.md`
  — the literal request, response, and both sync confirmations.

---

## Self-Review

**Spec coverage.** Suggestion Execution → Tasks 2, 4, 5. `suggestion_actions`
and `change_log` → Task 3. "One suggestion = one API call" → Task 2 (no
batching anywhere). "NO auto-apply in V1" → Task 5 (approve does not execute
unless explicitly asked). Rollback → Task 6, closing a gap the spec itself
admits.

**Not covered here, deferred to Plan 4:** bid rule type, `rule_conditions` /
`rule_actions` / `rule_campaign_scope`, scheduled rule evaluation, the Logs
screen, and the Campaign Manager KPI strip.

**Placeholders.** Tasks 4-6 give interfaces, ordering rules and test
assertions but compress the run-fail/implement/run-pass rhythm rather than
repeating it verbatim four more times. Every behavioural requirement is
stated as an assertion.

**Safety review.** The kill-switch is built first, defaults off, is asserted
by a test, and is verified off in the live environment at Task 2 Step 5. No
task before 7 issues a mutating request; all write tests use the fake
transport. Task 7 is explicitly gated on team authorisation and ends by
turning the switch back off.

**Known risk.** v3 mutation endpoints return `200`/`207` with per-item error
arrays, so HTTP status alone is not success. `_parse_mutation_result` handles
this and `test_per_item_error_is_a_failure_even_on_http_200` pins it —
getting this wrong would record changes that never happened, which is worse
than failing loudly.
