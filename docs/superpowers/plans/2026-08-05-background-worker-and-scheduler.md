# PPC OS Background Worker & Scheduler Implementation Plan (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Amazon syncing out of the HTTP request into a Celery worker with job state persisted in the existing `sync_jobs` table, so a 2-hour sync can be triggered from the UI and watched to completion.

**Architecture:** A Redis service is added to Docker Compose as a Celery broker and result backend. A new `worker` container runs Celery with the prefork pool — chosen over ARQ because the codebase uses synchronous SQLAlchemy/psycopg2, and prefork runs that natively without async bridging. `POST /sync-all` enqueues a task and returns `202` immediately with a job id. The worker writes progress to `sync_jobs`, and the existing `GET /sync-status` endpoint reads from that table instead of the in-memory `_sync_jobs` dict. Celery Beat provides periodic syncs.

**Tech Stack:** Python 3.12, Celery 5.4 (prefork), Redis 7, FastAPI 0.111, SQLAlchemy 2.0 (sync/psycopg2), Alembic, PostgreSQL 16, Next.js 14.

## Global Constraints

Carried forward from Plan 1 and the team's original constraints:

- "No write operations to Amazon Ads. Read-only only."
- "Rules never apply Amazon changes. Rules only create suggestions."
- "Do NOT hardcode secrets"
- "Do NOT modify historical migrations" — adding a **new** migration is fine; editing 001–011 is not.
- "Do NOT redesign architecture/database" — reuse the existing `sync_jobs` table; additive columns only.
- "All real mode errors must be readable."
- `errors[]` / `partial` contract from Plan 1 must be preserved in job results.
- Alembic head is currently `011`. The new migration is `012`.

## Prerequisites

Plan 1 must be merged or on the working branch. This plan assumes:

- `PartialFetchError` exists and `sync_*` return `errors[]` / `partial`
- `settings.amazon_report_poll_max_attempts` defaults to 1440 (4 hours)
- 19 tests pass

## What already exists (do not rebuild)

Verified 2026-08-05 — three things the team already built that this plan reuses:

| Existing | Location | Implication |
|---|---|---|
| Node proxy with 20-min timeout that survives browser close | `frontend/app/api/proxy-sync/[...path]/route.ts` | Once `/sync-all` returns 202 instantly, this stops mattering — but leave it in place for the direct per-level sync endpoints |
| `getSyncStatus()` API client method | `frontend/lib/api.ts:127` | No new client method needed |
| Account detail page already polls `sync-status` | `frontend/app/accounts/[id]/page.tsx` | **Polling already works.** It only breaks because the backend reads an in-memory dict. Fixing the backend fixes the UI with no frontend change. |
| `sync_jobs` table with status/error_message/retry_count and indexes | migration `009` or earlier; confirmed live in Postgres | Reuse it. No code has ever touched it. |

Existing `sync_jobs` columns (verified against the live database):

```
id uuid PK default gen_random_uuid()
job_type varchar(30) NOT NULL
profile_id uuid NULL
date_range_start date NULL
date_range_end date NULL
status varchar(20) NOT NULL default 'queued'
started_at timestamptz NULL
finished_at timestamptz NULL
records_synced int NOT NULL default 0
error_message text NULL
retry_count int NOT NULL default 0
created_at timestamptz NOT NULL default now()
Indexes: pkey, idx_sync_jobs_profile (profile_id), idx_sync_jobs_type_status (job_type, status, started_at DESC)
```

Two columns are missing for our purpose: syncs are per **seller account**, not
per profile, and the current in-memory job carries a nested `result` dict.
Migration `012` adds both additively.

## File Structure

**Created:**

- `backend/app/worker/__init__.py` — empty package marker
- `backend/app/worker/celery_app.py` — Celery application, broker/backend config, Beat schedule
- `backend/app/worker/tasks.py` — the `sync_account` task; the only place worker→service wiring lives
- `backend/app/modules/sync_jobs/__init__.py` — empty
- `backend/app/modules/sync_jobs/models.py` — `SyncJob` SQLAlchemy model mapping the existing table
- `backend/app/modules/sync_jobs/repository.py` — create/claim/complete/fail/latest-for-account
- `backend/alembic/versions/012_sync_jobs_account_and_result.py` — additive columns
- `backend/tests/modules/test_sync_jobs_repository.py`
- `backend/tests/worker/__init__.py`, `backend/tests/worker/test_tasks.py`

**Modified:**

- `docker-compose.yml` — add `redis` service and `worker` service
- `backend/requirements.txt` — `celery[redis]==5.4.0`, `redis==5.0.8`
- `backend/app/config.py` — `redis_url`, `sync_schedule_hours`
- `backend/app/modules/campaigns/router.py` — `/sync-all` enqueues; `/sync-status` reads DB; **delete** `_sync_jobs` dict, `_sync_lock`, `_run_sync_background` and the `threading` import
- `.env.example` — document `REDIS_URL`, `SYNC_SCHEDULE_HOURS`

**Not modified:** any frontend file. The existing polling works once the
backend is DB-backed. Verified in Task 5 rather than assumed.

---

### Task 1: Redis, Celery scaffolding, and a worker container

Prove the plumbing works before any real sync logic touches it.

**Files:**
- Create: `backend/app/worker/__init__.py`, `backend/app/worker/celery_app.py`
- Modify: `docker-compose.yml`, `backend/requirements.txt`, `backend/app/config.py`, `.env.example`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `settings.redis_url: str` (default `redis://redis:6379/0`)
  - `app.worker.celery_app.celery_app` — the Celery application object
  - `app.worker.celery_app.ping() -> str` — a trivial task returning `"pong"`, used only to verify the plumbing

- [ ] **Step 1: Add the dependencies**

Append to `backend/requirements.txt`:

```
# Background worker (Plan 2)
celery[redis]==5.4.0
redis==5.0.8
```

- [ ] **Step 2: Add the settings**

In `backend/app/config.py`, after the Amazon report poll settings:

```python
    # Background worker (Celery + Redis)
    redis_url: str = "redis://redis:6379/0"
    # Periodic full sync interval. 0 disables the schedule entirely.
    sync_schedule_hours: int = 6
```

- [ ] **Step 3: Create the Celery application**

Create `backend/app/worker/__init__.py` (empty) and
`backend/app/worker/celery_app.py`:

```python
"""Celery application for background Amazon syncs.

Pool choice: prefork (the default). The codebase uses synchronous
SQLAlchemy + psycopg2, which prefork runs natively. An asyncio worker
(ARQ, or Celery's gevent pool) would require bridging every blocking DB
and HTTP call, for no benefit here — these tasks are long and few, not
numerous and short.

Task time limits are deliberately generous: Amazon report generation was
measured at 23-40 minutes per report on the live account, and a full
90-day sync is 9 reports.
"""
import logging

from celery import Celery

from app.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "ppc_os",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # A full sync is hours, not seconds. soft < hard so the task can
    # record its own failure into sync_jobs before being killed.
    task_soft_time_limit=6 * 60 * 60,
    task_time_limit=6 * 60 * 60 + 300,
    # Never silently run the same account's sync twice in parallel.
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)


@celery_app.task(name="ping")
def ping() -> str:
    """Plumbing check only — not used by application code."""
    return "pong"
```

- [ ] **Step 4: Add `redis` and `worker` services to compose**

In `docker-compose.yml`, add a `redis` service and a `worker` service. The
worker reuses the `api` image (same code, different command) and joins the
same network. It does **not** expose a port.

```yaml
  redis:
    image: redis:7-alpine
    command: ["redis-server", "--save", "", "--appendonly", "no"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
    networks:
      - ppc_net

  worker:
    build:
      context: ./backend
    command: ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=info", "--concurrency=2"]
    volumes:
      - ./backend/app:/app/app
      - ./backend/tests:/app/tests
      - ./backend/pytest.ini:/app/pytest.ini
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      REDIS_URL: redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    dns:
      - 8.8.8.8
      - 8.8.4.4
    networks:
      - ppc_net
```

Note the `worker` service overrides the image's ENTRYPOINT via `command`.
The `api` entrypoint runs migrations and seeds users; the worker must not.
Because the Dockerfile uses `ENTRYPOINT ["/app/docker-entrypoint.sh"]`,
`command` alone will be passed as arguments to it. Add an explicit
`entrypoint: []` to the worker service to clear it:

```yaml
    entrypoint: []
```

Also add `REDIS_URL: redis://redis:6379/0` to the existing `api` service's
`environment` block so the API can enqueue.

- [ ] **Step 5: Document the new env vars**

Append to `.env.example`:

```
# ── Background worker (Plan 2) ─────────────────────────────────────────────
REDIS_URL=redis://redis:6379/0
# Hours between automatic full syncs. 0 disables the schedule.
SYNC_SCHEDULE_HOURS=6
```

- [ ] **Step 6: Build and verify the plumbing end to end**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose build api worker && docker compose up -d && sleep 20 && docker compose ps
```

Expected: `postgres`, `redis`, `api`, `worker`, `frontend` all running;
`redis` healthy.

Then prove a task actually round-trips through Redis:

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -c "
from app.worker.celery_app import ping
r = ping.delay()
print('task id:', r.id)
print('result:', r.get(timeout=30))
"
```

Expected: `result: pong`. If this hangs, the worker is not consuming —
check `docker compose logs worker` before continuing. **Do not proceed
until `pong` comes back**; every later task depends on this working.

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/app/config.py backend/app/worker docker-compose.yml .env.example
git commit -m "feat: add Redis broker and Celery worker container"
```

---

### Task 2: `SyncJob` model, migration 012, and repository

**Files:**
- Create: `backend/alembic/versions/012_sync_jobs_account_and_result.py`
- Create: `backend/app/modules/sync_jobs/__init__.py`, `models.py`, `repository.py`
- Test: `backend/tests/modules/test_sync_jobs_repository.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  ```python
  class SyncJob(Base):                      # maps existing sync_jobs table
      id: uuid.UUID
      job_type: str                          # 'sync_all' | 'sync_performance'
      seller_account_id: uuid.UUID | None    # added by migration 012
      profile_id: uuid.UUID | None
      status: str                            # queued|running|completed|failed
      started_at / finished_at: datetime | None
      records_synced: int
      error_message: str | None
      retry_count: int
      result_json: dict | None                # added by migration 012
      created_at: datetime

  class SyncJobRepository:
      def create(self, job_type: str, seller_account_id: uuid.UUID) -> SyncJob
      def mark_running(self, job_id: uuid.UUID) -> SyncJob | None
      def mark_completed(self, job_id: uuid.UUID, result: dict, records: int) -> SyncJob | None
      def mark_failed(self, job_id: uuid.UUID, error: str) -> SyncJob | None
      def latest_for_account(self, seller_account_id: uuid.UUID) -> SyncJob | None
      def has_active(self, seller_account_id: uuid.UUID) -> bool   # queued or running
  ```

- [ ] **Step 1: Write the migration**

Create `backend/alembic/versions/012_sync_jobs_account_and_result.py`.
Additive only — no existing migration is touched.

```python
"""add seller_account_id and result_json to sync_jobs

Revision ID: 012
Revises: 011
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Syncs are triggered per seller account; the table only had profile_id.
    op.add_column(
        "sync_jobs",
        sa.Column(
            "seller_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("seller_accounts.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    # The in-memory job state carried a nested result dict; persist it.
    op.add_column(
        "sync_jobs",
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "idx_sync_jobs_account_created",
        "sync_jobs",
        ["seller_account_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_sync_jobs_account_created", table_name="sync_jobs")
    op.drop_column("sync_jobs", "result_json")
    op.drop_column("sync_jobs", "seller_account_id")
```

- [ ] **Step 2: Apply the migration and verify**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api alembic upgrade head && docker compose exec -T postgres psql -U ppc_os -d ppc_os -c "\d sync_jobs"
```

Expected: `seller_account_id` and `result_json` present; `alembic_version`
now `012`.

- [ ] **Step 3: Write the failing test**

Create `backend/tests/modules/test_sync_jobs_repository.py`. These are pure
unit tests over the model's transitions using an in-memory object, so no
database is required:

```python
"""SyncJob status transitions must be explicit and total."""
import uuid
from datetime import datetime, timezone as tz

from app.modules.sync_jobs.models import SyncJob
from app.modules.sync_jobs.repository import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    ACTIVE_STATUSES,
)


def test_status_constants_are_distinct():
    all_statuses = {JOB_STATUS_QUEUED, JOB_STATUS_RUNNING, JOB_STATUS_COMPLETED, JOB_STATUS_FAILED}
    assert len(all_statuses) == 4


def test_active_statuses_are_exactly_queued_and_running():
    """has_active() must block a second sync while one is queued OR running."""
    assert set(ACTIVE_STATUSES) == {JOB_STATUS_QUEUED, JOB_STATUS_RUNNING}


def test_sync_job_defaults():
    job = SyncJob(job_type="sync_all", seller_account_id=uuid.uuid4())

    assert job.status is None or job.status == JOB_STATUS_QUEUED
    assert job.error_message is None
    assert job.result_json is None


def test_status_fits_column_width():
    """status is varchar(20) — a longer constant would raise at runtime."""
    for s in (JOB_STATUS_QUEUED, JOB_STATUS_RUNNING, JOB_STATUS_COMPLETED, JOB_STATUS_FAILED):
        assert len(s) <= 20


def test_job_type_fits_column_width():
    """job_type is varchar(30)."""
    for t in ("sync_all", "sync_performance"):
        assert len(t) <= 30
```

- [ ] **Step 4: Run to verify it fails**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/modules/test_sync_jobs_repository.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.modules.sync_jobs'`.

- [ ] **Step 5: Create the model**

Create `backend/app/modules/sync_jobs/__init__.py` (empty) and
`models.py`:

```python
"""SQLAlchemy model for the pre-existing sync_jobs table.

The table was created by an earlier migration and never used by any code —
job state lived in an in-memory dict in campaigns/router.py instead, which
was lost on restart and invisible across worker processes. This model wires
it up. Column names and types mirror the live table exactly.
"""
import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type = Column(String(30), nullable=False)
    seller_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("seller_accounts.id", ondelete="CASCADE"),
        nullable=True,
    )
    profile_id = Column(UUID(as_uuid=True), nullable=True)
    date_range_start = Column(Date, nullable=True)
    date_range_end = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default="queued")
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    records_synced = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    result_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

- [ ] **Step 6: Create the repository**

Create `backend/app/modules/sync_jobs/repository.py`:

```python
"""Persistence for background sync job state.

Replaces the in-memory _sync_jobs dict in campaigns/router.py. Because job
state now lives in Postgres, it survives container restarts and is visible
to every API worker and Celery worker — which the dict was not.
"""
import uuid
from datetime import datetime, timezone as tz

from sqlalchemy.orm import Session

from app.modules.sync_jobs.models import SyncJob

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"

# A second sync must be refused while one is queued or already running.
ACTIVE_STATUSES = (JOB_STATUS_QUEUED, JOB_STATUS_RUNNING)


class SyncJobRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, job_type: str, seller_account_id: uuid.UUID) -> SyncJob:
        job = SyncJob(
            job_type=job_type,
            seller_account_id=seller_account_id,
            status=JOB_STATUS_QUEUED,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def _get(self, job_id: uuid.UUID) -> SyncJob | None:
        return self.db.query(SyncJob).filter(SyncJob.id == job_id).one_or_none()

    def mark_running(self, job_id: uuid.UUID) -> SyncJob | None:
        job = self._get(job_id)
        if job is None:
            return None
        job.status = JOB_STATUS_RUNNING
        job.started_at = datetime.now(tz.utc)
        self.db.commit()
        self.db.refresh(job)
        return job

    def mark_completed(self, job_id: uuid.UUID, result: dict, records: int) -> SyncJob | None:
        job = self._get(job_id)
        if job is None:
            return None
        job.status = JOB_STATUS_COMPLETED
        job.finished_at = datetime.now(tz.utc)
        job.result_json = result
        job.records_synced = records
        self.db.commit()
        self.db.refresh(job)
        return job

    def mark_failed(self, job_id: uuid.UUID, error: str) -> SyncJob | None:
        job = self._get(job_id)
        if job is None:
            return None
        job.status = JOB_STATUS_FAILED
        job.finished_at = datetime.now(tz.utc)
        # error_message is TEXT but keep it sane for the UI.
        job.error_message = error[:4000]
        self.db.commit()
        self.db.refresh(job)
        return job

    def latest_for_account(self, seller_account_id: uuid.UUID) -> SyncJob | None:
        return (
            self.db.query(SyncJob)
            .filter(SyncJob.seller_account_id == seller_account_id)
            .order_by(SyncJob.created_at.desc())
            .first()
        )

    def has_active(self, seller_account_id: uuid.UUID) -> bool:
        return (
            self.db.query(SyncJob)
            .filter(
                SyncJob.seller_account_id == seller_account_id,
                SyncJob.status.in_(ACTIVE_STATUSES),
            )
            .count()
            > 0
        )
```

- [ ] **Step 7: Run to verify it passes**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests -q
```

Expected: 24 passed (19 from Plan 1 + 5 new).

- [ ] **Step 8: Commit**

```bash
git add backend/alembic/versions/012_sync_jobs_account_and_result.py backend/app/modules/sync_jobs backend/tests/modules/test_sync_jobs_repository.py
git commit -m "feat: wire up the unused sync_jobs table with model and repository"
```

---

### Task 3: The `sync_account` Celery task

**Files:**
- Create: `backend/app/worker/tasks.py`
- Test: `backend/tests/worker/__init__.py`, `backend/tests/worker/test_tasks.py`

**Interfaces:**
- Consumes: `SyncJobRepository` (Task 2), `celery_app` (Task 1),
  `CampaignSyncService.sync_all`, `PerformanceService.sync_performance`
- Produces:
  ```python
  @celery_app.task(name="sync_account", bind=True)
  def sync_account(self, job_id: str, account_id: str, perf_days: int | None = None) -> dict
  ```
  Returns the same shape the old `_run_sync_background` produced, so the
  `sync-status` response contract is unchanged:
  `{"campaigns": {...}, "ad_groups": {...}, "targets": {...}, "perf_campaign_rows": int, "perf_ad_group_rows": int, "perf_target_rows": int, "errors": [...]}`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/worker/__init__.py` (empty) and
`backend/tests/worker/test_tasks.py`:

```python
"""The sync task must record its own outcome into sync_jobs, always."""
import inspect

from app.worker import tasks


def test_sync_account_task_exists_and_is_registered():
    assert hasattr(tasks, "sync_account")
    assert tasks.sync_account.name == "sync_account"


def test_task_opens_its_own_db_session():
    """A Celery task has no request-scoped session — it must make its own."""
    src = inspect.getsource(tasks.sync_account)
    assert "SessionLocal()" in src, "task must create its own DB session"
    assert "finally" in src and "close()" in src, "session must always be closed"


def test_task_marks_running_then_completed_or_failed():
    """Every exit path must leave the job in a terminal state."""
    src = inspect.getsource(tasks.sync_account)
    assert "mark_running" in src
    assert "mark_completed" in src
    assert "mark_failed" in src


def test_failure_is_recorded_before_reraise():
    """A crashed sync must not leave the job stuck in 'running' forever.

    This is the bug the in-memory dict had: a container restart mid-sync
    left no record at all.
    """
    src = inspect.getsource(tasks.sync_account)
    failed_at = src.index("mark_failed")
    # mark_failed must appear inside the except block, before any raise
    # that follows it.
    assert "except Exception" in src
    assert src.index("except Exception") < failed_at


def test_performance_failure_does_not_abort_structure_sync():
    """Structure sync results must be kept even if the perf sync fails.

    Matches the pre-existing behaviour in _run_sync_background, which
    treated a perf failure as non-fatal.
    """
    src = inspect.getsource(tasks.sync_account)
    assert "perf_error" in src, "perf failure must be recorded, not fatal"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/worker -q
```

Expected: `ModuleNotFoundError: No module named 'app.worker.tasks'`.

- [ ] **Step 3: Write the task**

Create `backend/app/worker/tasks.py`. This is a direct port of
`_run_sync_background` from `campaigns/router.py:78-151`, with the
in-memory dict replaced by `SyncJobRepository`:

```python
"""Background Amazon sync tasks.

Ported from the daemon thread previously in campaigns/router.py. Two
things changed: job state is persisted in sync_jobs rather than a
process-local dict, and the task can run for hours because nothing is
holding an HTTP connection open.
"""
import logging
import traceback
import uuid

from app.database import SessionLocal
from app.modules.accounts.repository import SellerAccountRepository
from app.modules.campaigns.service import CampaignSyncService
from app.modules.sync_jobs.repository import SyncJobRepository
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="sync_account", bind=True)
def sync_account(self, job_id: str, account_id: str, perf_days: int | None = None) -> dict:
    """Full sync: campaign/ad group/target structure, then performance.

    Args:
        job_id:     sync_jobs row to report progress into.
        account_id: SellerAccount UUID as a string (Celery args are JSON).
        perf_days:  Days of performance history; None uses the service default.
    """
    # Imported here to avoid a circular import at module load.
    from app.modules.performance.service import PerformanceService

    job_uuid = uuid.UUID(job_id)
    account_uuid = uuid.UUID(account_id)

    db = SessionLocal()
    jobs = SyncJobRepository(db)
    try:
        jobs.mark_running(job_uuid)

        account = SellerAccountRepository(db).get_by_id(account_uuid)
        if account is None:
            raise ValueError(f"Seller account {account_uuid} not found")

        # ── Structure ──────────────────────────────────────────────────
        result = CampaignSyncService(db).sync_all(account)
        logger.warning("[worker] structure sync done for account %s", account_uuid)

        # ── Performance (non-fatal: keep structure results either way) ──
        perf_rows = {
            "perf_campaign_rows": 0,
            "perf_ad_group_rows": 0,
            "perf_target_rows": 0,
        }
        try:
            perf = PerformanceService(db).sync_performance(
                account, days=perf_days, force_full=True
            )
            perf_rows["perf_campaign_rows"] = perf.campaign_rows
            perf_rows["perf_ad_group_rows"] = perf.ad_group_rows
            perf_rows["perf_target_rows"] = perf.target_rows
            logger.warning(
                "[worker] perf sync done camp=%d ag=%d tgt=%d",
                perf.campaign_rows, perf.ad_group_rows, perf.target_rows,
            )
        except Exception as perf_exc:
            logger.error("[worker] perf sync failed (non-fatal): %s", perf_exc)
            perf_rows["perf_error"] = str(perf_exc)

        if isinstance(result, dict):
            result.update(perf_rows)

        # Surface Plan 1's per-level errors[] at the top level so the UI
        # can show a partial sync as partial rather than as success.
        collected: list[str] = []
        for level in ("campaigns", "ad_groups", "targets"):
            section = result.get(level) if isinstance(result, dict) else None
            if isinstance(section, dict):
                collected.extend(section.get("errors") or [])
        if perf_rows.get("perf_error"):
            collected.append(f"performance: {perf_rows['perf_error']}")
        result["errors"] = collected

        records = (
            result.get("campaigns", {}).get("upserted", 0)
            + result.get("ad_groups", {}).get("upserted", 0)
            + result.get("targets", {}).get("upserted", 0)
        )
        jobs.mark_completed(job_uuid, result, records)
        return result

    except Exception as exc:
        logger.error("[worker] sync_account FAILED job=%s: %s\n%s",
                     job_id, exc, traceback.format_exc())
        try:
            db.rollback()
        except Exception:
            pass
        # Record the failure before re-raising so the job never sticks in
        # 'running' — the exact failure mode the in-memory dict had.
        jobs.mark_failed(job_uuid, f"{type(exc).__name__}: {exc}")
        raise
    finally:
        db.close()
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests -q
```

Expected: 29 passed.

- [ ] **Step 5: Restart the worker so it picks up the new task**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose restart worker && sleep 10 && docker compose logs worker --tail 20 | grep -iE "sync_account|ready|error"
```

Expected: `sync_account` appears in the registered-tasks list and the
worker reports ready. A `KeyError`/import error here means the task module
failed to load — fix before proceeding.

- [ ] **Step 6: Commit**

```bash
git add backend/app/worker/tasks.py backend/tests/worker
git commit -m "feat: add sync_account Celery task with persisted job state"
```

---

### Task 4: Router enqueues instead of threading; status reads the database

This is where the 2-minute timeout problem actually dies.

**Files:**
- Modify: `backend/app/modules/campaigns/router.py` — `sync_all` (lines ~376-409), `get_sync_status` (lines ~314-373); delete `_sync_jobs`, `_sync_lock`, `_run_sync_background`, `import threading`
- Test: `backend/tests/modules/test_sync_router_enqueue.py`

**Interfaces:**
- Consumes: `sync_account` task (Task 3), `SyncJobRepository` (Task 2)
- Produces: `POST /accounts/{id}/sync-all` returns `202` with
  `{"message": str, "status": "queued", "job_id": str}`.
  `GET /accounts/{id}/sync-status` keeps its existing top-level shape —
  `campaigns` / `ad_groups` / `targets` counts plus `sync_job` — so the
  existing frontend polling continues to work unchanged. The `sync_job`
  object gains `job_id` and `records_synced`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/modules/test_sync_router_enqueue.py`:

```python
"""sync-all must enqueue and return immediately; no threads, no dict."""
import inspect

from app.modules.campaigns import router as campaigns_router


def test_in_memory_job_state_is_gone():
    """The _sync_jobs dict and its lock caused the multi-worker bug."""
    src = inspect.getsource(campaigns_router)

    assert "_sync_jobs" not in src, "in-memory job dict must be deleted"
    assert "_sync_lock" not in src, "in-memory lock must be deleted"
    assert "import threading" not in src, "threading is no longer used"
    assert "_run_sync_background" not in src, "daemon thread runner must be deleted"


def test_sync_all_enqueues_a_celery_task():
    src = inspect.getsource(campaigns_router.sync_all)

    assert "sync_account" in src, "must enqueue the Celery task"
    assert ".delay(" in src or ".apply_async(" in src, "must dispatch asynchronously"
    assert "202" in src, "must return 202 Accepted immediately"


def test_sync_all_refuses_concurrent_runs_via_database():
    """The 409 guard must consult the DB, not process-local state."""
    src = inspect.getsource(campaigns_router.sync_all)

    assert "has_active" in src, "concurrency guard must query sync_jobs"
    assert "409" in src


def test_sync_status_reads_job_from_database():
    src = inspect.getsource(campaigns_router.get_sync_status)

    assert "latest_for_account" in src, "status must read the persisted job"
    assert "sync_job" in src, "existing response key must be preserved"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/modules/test_sync_router_enqueue.py -q
```

Expected: all 4 fail.

- [ ] **Step 3: Delete the in-memory machinery**

In `backend/app/modules/campaigns/router.py`:

1. Remove `import threading` from the imports.
2. Delete the block:
   ```python
   # ── In-memory sync job state ────────────────────────────────────────────────
   _sync_jobs: dict[str, dict] = {}
   _sync_lock = threading.Lock()
   ```
3. Delete the entire `_run_sync_background` function (the `# ── Background
   sync runner ──` section) — its logic now lives in
   `app/worker/tasks.py`.

- [ ] **Step 4: Replace `sync_all` with an enqueue**

```python
@sync_router.post("/{account_id}/sync-all")
def sync_all(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> JSONResponse:
    """
    Enqueue a full sync (structure + performance) and return immediately.

    Returns 202 with a job_id. Poll GET /accounts/{id}/sync-status for
    progress. Returns 409 if a sync is already queued or running for this
    account — checked against the sync_jobs table, so the guard holds
    across API workers and container restarts.
    """
    _get_account_or_404(account_id, db)

    jobs = SyncJobRepository(db)
    if jobs.has_active(account_id):
        return JSONResponse(
            status_code=409,
            content={"detail": "Sync already queued or running for this account"},
        )

    job = jobs.create(job_type="sync_all", seller_account_id=account_id)
    sync_account.delay(str(job.id), str(account_id))

    _audit(db, current_user.id, account_id, "sync_all_enqueued", {"job_id": str(job.id)})
    logger.warning("[sync_all] enqueued job %s for account %s", job.id, account_id)

    return JSONResponse(status_code=202, content={
        "message": "Sync queued — poll GET /accounts/{id}/sync-status for progress",
        "status": "queued",
        "job_id": str(job.id),
    })
```

Add the imports at the top of the file:

```python
from app.modules.sync_jobs.repository import SyncJobRepository
from app.worker.tasks import sync_account
```

- [ ] **Step 5: Point `get_sync_status` at the database**

Keep the existing counts CTE and its `SET LOCAL statement_timeout = 0`
exactly as they are. Replace only the trailing `with _sync_lock:` block and
the `sync_job` section of the response:

```python
    job = SyncJobRepository(db).latest_for_account(account_id)

    return JSONResponse(content={
        "campaigns": {"count": int(row.campaign_count or 0), "last_synced_at": _iso(row.campaign_last_at)},
        "ad_groups": {"count": int(row.ad_group_count or 0), "last_synced_at": _iso(row.ad_group_last_at)},
        "targets":   {"count": int(row.target_count or 0),   "last_synced_at": _iso(row.target_last_at)},
        "sync_job": {
            "job_id":         str(job.id) if job else None,
            "running":        job.status in ("queued", "running") if job else False,
            "status":         job.status if job else None,
            "started_at":     _iso(job.started_at) if job else None,
            "completed_at":   _iso(job.finished_at) if job else None,
            "error":          job.error_message if job else None,
            "result":         job.result_json if job else None,
            "records_synced": job.records_synced if job else 0,
        },
    })
```

`running` is retained with its original meaning so the existing frontend
polling logic keeps working; `status` is added for a richer UI later.

- [ ] **Step 6: Run the tests and restart both services**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests -q && docker compose restart api worker && sleep 15 && curl -s http://localhost:8000/health
```

Expected: 33 passed, then a healthy `/health`.

- [ ] **Step 7: Verify a real enqueue returns instantly**

The headline check: this used to hold the connection for hours.

```bash
cd /Users/tsth/Downloads/helium/ppc-os && TOKEN=$(ADMIN_EMAIL=$(grep -E '^SEED_ADMIN_EMAIL=' .env | cut -d= -f2-); ADMIN_PW=$(grep -E '^SEED_ADMIN_PASSWORD=' .env | cut -d= -f2-); curl -s -X POST http://localhost:8000/auth/login -H 'Content-Type: application/json' -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PW\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])") && time curl -s -X POST "http://localhost:8000/accounts/85e0e890-6baf-45ef-b8de-026c07f050e0/sync-all" -H "Authorization: Bearer $TOKEN"
```

Expected: a `202` with a `job_id` in **under one second**.

Then confirm a second call is refused, and that status reflects the worker:

```bash
cd /Users/tsth/Downloads/helium/ppc-os && curl -s -X POST "http://localhost:8000/accounts/85e0e890-6baf-45ef-b8de-026c07f050e0/sync-all" -H "Authorization: Bearer $TOKEN" ; echo ; curl -s "http://localhost:8000/accounts/85e0e890-6baf-45ef-b8de-026c07f050e0/sync-status" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: `409` on the second POST; `sync_job.status` is `queued` or
`running` with a real `job_id`.

- [ ] **Step 8: Verify job state survives a restart**

This is the behaviour the in-memory dict could never provide.

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose restart api && sleep 15 && curl -s "http://localhost:8000/accounts/85e0e890-6baf-45ef-b8de-026c07f050e0/sync-status" -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['sync_job'])"
```

Expected: the job is still reported, with its id and status intact.
Previously this returned an empty object.

- [ ] **Step 9: Commit**

```bash
git add backend/app/modules/campaigns/router.py backend/tests/modules/test_sync_router_enqueue.py
git commit -m "feat: sync-all enqueues to Celery; status reads persisted job state"
```

---

### Task 5: Confirm the existing frontend polling works unchanged

The account detail page already polls `sync-status`. This task **verifies**
that claim rather than assuming it, and fixes the page only if needed.

**Files:**
- Read: `frontend/app/accounts/[id]/page.tsx`, `frontend/lib/api.ts`, `frontend/lib/types.ts`
- Modify: only if verification fails

**Interfaces:**
- Consumes: the `sync-status` contract from Task 4
- Produces: no new interface

- [ ] **Step 1: Check what the page expects from `sync_job`**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && grep -n "sync_job\|syncJob\|running\|SyncStatus" frontend/app/accounts/\[id\]/page.tsx frontend/lib/types.ts
```

Compare each field the page reads against the `sync_job` object Task 4
returns. Task 4 preserves `running`, `started_at`, `completed_at`, `error`
and `result`, and adds `job_id`, `status`, `records_synced`.

- [ ] **Step 2: If `types.ts` declares a `SyncStatus` type, add the new fields**

TypeScript will not fail on extra JSON keys, so this is only for editor
support. Add to the `sync_job` shape in `frontend/lib/types.ts`:

```typescript
  job_id: string | null
  status: string | null
  records_synced: number
```

- [ ] **Step 3: Verify in the browser**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose restart frontend && sleep 20 && curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/accounts
```

Then, signed in as the seed admin, open the account detail page, click
**Sync All**, and confirm: the button returns immediately (no hang), a
running state appears, and the state updates as the worker progresses.

- [ ] **Step 4: Confirm no console errors**

Open the browser devtools console on the account detail page during a
sync. Expected: no errors. A `TypeError` reading a `sync_job` field means
Task 4 dropped a key the page relies on — fix Task 4's response, not the
page.

- [ ] **Step 5: Commit (only if files changed)**

```bash
git add frontend/lib/types.ts
git commit -m "chore: extend SyncStatus type with persisted job fields"
```

If nothing changed, record that in the task notes and move on — a task
that correctly changes nothing is a valid outcome.

---

### Task 6: Periodic sync with Celery Beat

**Files:**
- Modify: `backend/app/worker/celery_app.py`, `docker-compose.yml`
- Create: `backend/app/worker/schedule.py`
- Test: `backend/tests/worker/test_schedule.py`

**Interfaces:**
- Consumes: `sync_account` (Task 3), `SyncJobRepository` (Task 2)
- Produces:
  ```python
  @celery_app.task(name="enqueue_scheduled_syncs")
  def enqueue_scheduled_syncs() -> dict   # {"enqueued": int, "skipped": int}
  ```
  Beat calls this on an interval; it fans out one `sync_account` per
  connected account, skipping any that already have an active job.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/worker/test_schedule.py`:

```python
"""The scheduler must fan out per account and never double-queue."""
import inspect

from app.config import settings
from app.worker import schedule


def test_scheduled_task_is_registered():
    assert schedule.enqueue_scheduled_syncs.name == "enqueue_scheduled_syncs"


def test_scheduler_skips_accounts_with_an_active_job():
    """Without this, a slow 4-hour sync would be re-queued every 6 hours."""
    src = inspect.getsource(schedule.enqueue_scheduled_syncs)
    assert "has_active" in src, "must skip accounts already syncing"


def test_scheduler_only_syncs_connected_accounts():
    """An account with no OAuth credential cannot sync — don't queue it."""
    src = inspect.getsource(schedule.enqueue_scheduled_syncs)
    assert "Credential" in src or "credential" in src


def test_schedule_can_be_disabled():
    """SYNC_SCHEDULE_HOURS=0 must mean no periodic schedule at all."""
    assert hasattr(settings, "sync_schedule_hours")
    from app.worker.celery_app import build_beat_schedule

    assert build_beat_schedule(0) == {}
    assert "enqueue-scheduled-syncs" in build_beat_schedule(6)
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests/worker/test_schedule.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.worker.schedule'`.

- [ ] **Step 3: Create the fan-out task**

Create `backend/app/worker/schedule.py`:

```python
"""Periodic sync fan-out.

Beat runs this on an interval; it enqueues one sync_account task per
connected seller account. Accounts that already have a queued or running
job are skipped — a full sync can take hours, and re-queueing one that is
still in flight would pile up work indefinitely.
"""
import logging

from app.database import SessionLocal
from app.modules.accounts.models import Credential, SellerAccount
from app.modules.sync_jobs.repository import SyncJobRepository
from app.worker.celery_app import celery_app
from app.worker.tasks import sync_account

logger = logging.getLogger(__name__)


@celery_app.task(name="enqueue_scheduled_syncs")
def enqueue_scheduled_syncs() -> dict:
    db = SessionLocal()
    try:
        jobs = SyncJobRepository(db)
        # Only accounts that completed OAuth can sync.
        accounts = (
            db.query(SellerAccount)
            .join(Credential, Credential.seller_account_id == SellerAccount.id)
            .all()
        )

        enqueued = 0
        skipped = 0
        for account in accounts:
            if jobs.has_active(account.id):
                logger.info("[beat] skipping account %s — sync already active", account.id)
                skipped += 1
                continue
            job = jobs.create(job_type="sync_all", seller_account_id=account.id)
            sync_account.delay(str(job.id), str(account.id))
            logger.warning("[beat] enqueued job %s for account %s", job.id, account.id)
            enqueued += 1

        return {"enqueued": enqueued, "skipped": skipped}
    finally:
        db.close()
```

- [ ] **Step 4: Add the Beat schedule builder**

In `backend/app/worker/celery_app.py`, add below the config block:

```python
def build_beat_schedule(hours: int) -> dict:
    """Return the Beat schedule, or {} when scheduling is disabled.

    Kept as a function so the disabled case is directly testable.
    """
    if hours <= 0:
        return {}
    return {
        "enqueue-scheduled-syncs": {
            "task": "enqueue_scheduled_syncs",
            "schedule": float(hours * 60 * 60),
        }
    }


celery_app.conf.beat_schedule = build_beat_schedule(settings.sync_schedule_hours)
```

Also add `"app.worker.schedule"` to the `include` list in the `Celery(...)`
constructor so Beat can find the task.

- [ ] **Step 5: Add the Beat container**

In `docker-compose.yml`, add a `beat` service — identical to `worker`
except for the command. Beat only schedules; it does not execute tasks.

```yaml
  beat:
    build:
      context: ./backend
    entrypoint: []
    command: ["celery", "-A", "app.worker.celery_app", "beat", "--loglevel=info"]
    volumes:
      - ./backend/app:/app/app
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      REDIS_URL: redis://redis:6379/0
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - ppc_net
```

- [ ] **Step 6: Verify tests and that Beat starts**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -m pytest tests -q && docker compose up -d beat && sleep 12 && docker compose logs beat --tail 15
```

Expected: 37 passed; Beat logs a configured schedule entry for
`enqueue-scheduled-syncs`.

- [ ] **Step 7: Verify the fan-out logic without waiting 6 hours**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose exec -T api python -c "
from app.worker.schedule import enqueue_scheduled_syncs
print(enqueue_scheduled_syncs.apply().get())
"
```

Expected: `{'enqueued': 1, 'skipped': 0}` — or `skipped: 1` if a sync from
Task 4 is still running, which is itself the guard working correctly.

- [ ] **Step 8: Commit**

```bash
git add backend/app/worker/ docker-compose.yml backend/tests/worker/test_schedule.py
git commit -m "feat: add Celery Beat schedule for periodic account syncs"
```

---

### Task 7: Pre-VPS hardening

Independent of Tasks 1-6 — can be done at any point, but **must** be done
before this leaves a laptop. Currently the API listens on all interfaces
with a published default password.

**Files:**
- Modify: `docker-compose.yml`, `frontend/Dockerfile`, `.env` (local, not committed), `.env.example`
- Create: `docs/DEPLOYMENT.md`

**Interfaces:**
- Consumes: nothing
- Produces: no code interface; a documented deployment posture

- [ ] **Step 1: Bind published ports to localhost only**

In `docker-compose.yml`, change the `api` and `frontend` port mappings so
they are not reachable from the network. A reverse proxy terminates TLS in
front of them in production.

```yaml
    # api
    ports:
      - "127.0.0.1:8000:8000"
```
```yaml
    # frontend
    ports:
      - "127.0.0.1:3000:3000"
```

Verify from another machine on the same network that `http://<mac-ip>:8000/health`
no longer answers, while `http://localhost:8000/health` still does.

- [ ] **Step 2: Give the frontend a production build**

`frontend/Dockerfile` currently ends with `CMD ["npm", "run", "dev"]`,
which runs the dev server with hot reload. Replace the final lines:

```dockerfile
RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start"]
```

Note `NEXT_PUBLIC_API_URL` is inlined at **build** time, so it must be
present as a build arg or env var during `npm run build`. The compose
`frontend.environment` block already sets `NEXT_PUBLIC_API_URL: /backend`;
for the production image add it as an `ARG`/`ENV` before `npm run build`:

```dockerfile
ARG NEXT_PUBLIC_API_URL=/backend
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
```

Keep a dev override so local work still has hot reload — either a
`docker-compose.override.yml` with `command: npm run dev`, or a separate
build target. Do not lose hot reload for daily development.

- [ ] **Step 3: Rotate every secret**

The current `.env` values were present in plaintext in a `Downloads`
folder and must be considered compromised. Generate fresh values:

```bash
cd /Users/tsth/Downloads/helium/ppc-os && echo "JWT_SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" && echo "POSTGRES_PASSWORD=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')" && docker compose exec -T api python -c "from cryptography.fernet import Fernet; print('FERNET_KEY=' + Fernet.generate_key().decode())"
```

**Order matters, and `FERNET_KEY` is destructive.** Rotating it makes every
stored Amazon refresh token undecryptable, so OAuth must be re-run for each
account afterwards. Sequence:

1. Change `JWT_SECRET_KEY` — invalidates existing logins only.
2. Change `POSTGRES_PASSWORD` — must be changed in `.env` **and** on the
   existing database role, or the app cannot connect:
   `ALTER USER ppc_os WITH PASSWORD '<new>';`
3. Change `FERNET_KEY` **last**, and immediately re-run the OAuth flow for
   every connected account.
4. Rotate `AMAZON_CLIENT_SECRET` in the Amazon Developer Console and update
   `.env` to match.
5. Change `SEED_ADMIN_PASSWORD` / `SEED_USER_PASSWORD` away from
   `ChangeMe123!`, then update the existing rows — the seed script is
   idempotent and will not overwrite existing users, so change those
   passwords through the app or with a one-off script.

- [ ] **Step 4: Write the deployment notes**

Create `docs/DEPLOYMENT.md` covering: the reverse proxy and TLS
requirement, that `AMAZON_REDIRECT_URI` must become
`https://<domain>/accounts/oauth/callback` **and** be re-registered in the
Amazon LWA app, the secret-rotation order above, and a `pg_dump` cron
example. Include the warning that `docker compose down -v` destroys the
database volume.

- [ ] **Step 5: Verify everything still runs after hardening**

```bash
cd /Users/tsth/Downloads/helium/ppc-os && docker compose down && docker compose up -d --build && sleep 40 && docker compose ps && curl -s http://localhost:8000/health && docker compose exec -T api python -m pytest tests -q | tail -3
```

Expected: all services up, health OK, 37 tests passing.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml frontend/Dockerfile .env.example docs/DEPLOYMENT.md
git commit -m "chore: harden for deployment — localhost binding, prod frontend build, docs"
```

---

## Self-Review

**Spec coverage.** Worker process → Tasks 1, 3. `sync_jobs` wiring and
deletion of the in-memory dict → Tasks 2, 4. UI status → Task 5.
Scheduler → Task 6. Pre-VPS hardening → Task 7. Bugs 5, 6 and 7 from the
original diagnosis are all addressed.

**Placeholders.** None. Task 5 is genuinely conditional — it verifies an
existing implementation and may correctly change nothing; that is stated
explicitly rather than left vague. Task 7 Step 4 specifies exactly what
`DEPLOYMENT.md` must contain.

**Type consistency.** `SyncJob` field names match the live table plus the
two columns added in migration `012`. `SyncJobRepository` method names
(`create`, `mark_running`, `mark_completed`, `mark_failed`,
`latest_for_account`, `has_active`) are spelled identically in Tasks 2, 3,
4 and 6. Status constants (`queued`, `running`, `completed`, `failed`) are
defined once in `repository.py` and reused. `sync_account(job_id: str,
account_id: str, perf_days: int | None)` takes strings because Celery
serialises arguments as JSON — matched at both the enqueue site (Task 4)
and the fan-out site (Task 6).

**Known risks.**

1. **Migration 012 assumes `alembic_version` is `011`.** Verified against
   the live database on 2026-08-05. Re-check before applying.
2. **`FERNET_KEY` rotation is destructive** — it invalidates every stored
   Amazon refresh token. Called out in Task 7 Step 3 with the required
   ordering.
3. **Two Celery containers share the `api` image**, so a `requirements.txt`
   change needs `docker compose build api worker beat`. Task 1 Step 6 and
   Task 7 Step 5 both use `--build`.
4. **Task 5 may reveal the frontend needs more than a type tweak.** If the
   page turns out not to poll the way the logs suggested, that becomes a
   real implementation task; stop and re-plan rather than improvising.

## Not in this plan

Deliberately excluded — these are product decisions, not repairs:

- Pushing changes back to Amazon (bid updates, pausing, negative keywords).
  The team's constraint is explicit: *"No write operations to Amazon Ads.
  Read-only only."* Adtomic does this; PPC OS does not, by design.
- Verifying the `orders` / `sales` columns, which were zero across every row
  in Plan 1's verification. Needs a 30-90 day pull compared against the
  Amazon Ads console — a data-validation task, not an engineering one.
- Multi-tenancy, user management UI, dayparting, keyword intelligence.
