# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PPC OS is an Amazon Advertising management tool: it syncs campaign, ad group,
keyword and search-term data from the Amazon Ads API into Postgres, applies
threshold rules to that data to produce **suggestions**, and — only after a
human approves each one — writes bid changes and negative keywords back to
Amazon.

The users are PPC managers, not engineers. When they ask how something works,
answer in terms of the screens (Campaign Manager, Keywords, Suggestions,
Rules, Logs), not in terms of modules.

## Everything runs in Docker

There is no local Python or Node setup. All six services come from
`docker compose`, and every command below runs inside a container.

```bash
docker compose up -d          # start (override file adds frontend hot reload)
docker compose ps             # api, worker, beat, postgres, redis, frontend
docker compose logs -f worker # background job output
```

App at `http://localhost:3000`, API at `http://localhost:8000`,
OpenAPI at `http://localhost:8000/docs`.

On a server, run the base file alone so the frontend serves a production
build instead of the dev server:

```bash
docker compose -f docker-compose.yml up -d
```

### Tests

```bash
docker compose exec api python -m pytest tests/ -q
docker compose exec api python -m pytest tests/modules/test_rules_execution.py -q     # one file
docker compose exec api python -m pytest tests/ -q -k "commit"                        # by name
docker compose exec frontend npx tsc --noEmit                                         # frontend typecheck
```

The suite is fast (<1s) because it has no database fixture. That is a real
limitation — see "Unit tests do not touch the database" below.

### Migrations

```bash
docker compose exec api alembic upgrade head
docker compose exec api alembic revision -m "description"
docker compose exec api alembic heads      # current: 015
```

`backend/alembic/` is bind-mounted. It did not used to be, and new migration
files were invisible inside the container — if a revision you just wrote
cannot be found, check the mount before debugging Alembic.

## Architecture

### Request path

Every backend module follows `router → service → repository → models`.
Routers own HTTP concerns and **transactions**; services own business logic;
repositories own SQL. Frontend calls go through `frontend/lib/api.ts` (never
`fetch` directly in a component) and land on the Next.js `/backend` rewrite
proxy, so all API calls are same-origin.

### Where the money-touching code lives

`backend/app/core/amazon_ads_write.py` is **the only module permitted to
mutate Amazon**, and it exposes exactly three operations: update keyword
bids, update target bids, create negative keywords. There is no
create-campaign and no delete anywhere in the app; `scripts/create_test_campaign.py`
is deliberately a standalone script outside the app so the write client can
never gain that capability.

Two invariants that are easy to break and expensive to get wrong:

- **`AMAZON_WRITE_ENABLED` defaults to `False`.** Every write function calls
  `assert_write_enabled()` first. Do not add a code path that bypasses it.
- **Amazon v3 mutations return HTTP 200/207 with per-item error arrays.** A
  2xx status does not mean the change was applied. `_parse_mutation_result`
  reports success only when there is at least one success *and* zero errors.
  Never treat the status code alone as the outcome.

The audit trail depends on ordering: `ExecutionService` records the attempt
in `suggestion_actions` **before** calling Amazon, and writes a `change_log`
row **only** when Amazon confirms the change. A failure therefore leaves an
attempt with no change_log row, and rollback reads `change_log`, so it can
never try to undo something that did not happen.

### Background work

Celery + Redis, prefork pool (the codebase is synchronous SQLAlchemy).
`app/worker/` holds the tasks; Beat schedules them:

| Task | Interval | Setting |
|---|---|---|
| `enqueue_scheduled_syncs` | 6h | `sync_schedule_hours` |
| `evaluate_all_rules` | 24h | `rule_schedule_hours` |
| `check_sync_health` | 30min | `health_check_interval_minutes` |

**Celery reads its task registry only at startup.** After adding or renaming
a task you must `docker compose restart worker beat`, or Beat will dispatch a
task the worker rejects with `KeyError` — silently, forever. This has bitten
this project twice.

**Commits are the caller's job in the rules module.** `RuleEngine` and the
rule repositories only `flush()`; in the API path the *router* commits. A
Celery task calling `RuleEngine` must commit itself or the entire evaluation
is rolled back at `db.close()` — while still logging success. This was a live
bug (see `tests/worker/test_rule_task_commits.py`). Other modules (campaigns,
performance, sync_jobs, execution) commit inside their repositories, so this
asymmetry is specific to rules.

### Sync and its failure modes

A sync is long — Amazon report generation was measured at 23–40 minutes per
report, and a full 90-day pull is nine reports. Task time limits are 6 hours
on purpose.

- Paginated list fetches raise `PartialFetchError` carrying the rows that
  *did* arrive. The service persists those rows and **skips the soft-delete
  sweep**, because a partial fetch would otherwise mark hundreds of thousands
  of live keywords as deleted.
- Long fetches outlive short-lived tokens. `_REFRESH_BUFFER_SECONDS` is 600
  (not 60) and `_post_list_paginated` takes a `token_getter` so a mid-fetch
  401 refreshes instead of losing the run.
- `sync_jobs.status` is constrained in the database to
  `queued|running|success|failed|partial`. Not `completed`. A sync with any
  errors is downgraded to `partial`, and `partial` counts as unhealthy.

### Profiles are the scoping unit

One seller account has several `ads_profiles` (US, CA, MX) and **almost every
table scopes by `profile_id`, not by account**. Rules, suggestions and
campaigns all belong to exactly one marketplace.

The frontend header has an account selector and a marketplace selector, and
the marketplace selector can be "All Profiles" (`currentProfileId === null`).
Any screen that needs a single profile must either query every profile in the
account and merge, or ask the user which one — **never silently pick the
first**. Doing that made the Rules page report "No rules yet" while two rules
existed. Data screens should also explain *which* marketplace has data rather
than implying a sync is needed; see `frontend/lib/emptyState.ts`.

### Suggestions are deterministic, not AI

Both engines (`modules/suggestions/service.py` and `modules/rules/service.py`)
produce suggestions from numeric thresholds a user can read and edit. Do not
describe them as AI-generated in code comments or UI copy.

Both engines create suggestions, so shared correctness rules live in
`modules/suggestions/asin.py` rather than in either engine — an ASIN search
term is a product-targeting placement, and a keyword-typed suggestion for it
is unactionable on Amazon. Fixing one engine and not the other has already
happened once.

## Things that look fine and are not

**Numeric values arrive from the API as strings.** `spend`, `sales` and the
rest serialise as `'8.97'`, so a plain `<`/`>` comparison sorts them
alphabetically — `$8.97` above `$27.71`. `DataTable` coerces before comparing;
any new sort logic must too.

**Unit tests do not touch the database.** The suite passes without Postgres,
which means schema-level constraints are invisible to it. A `CHECK`
constraint violation in `sync_jobs` shipped green and only surfaced on a real
insert. For anything touching schema constraints, verify against the running
database as well:

```bash
docker compose exec postgres psql -U ppc_os -d ppc_os -c "\d+ table_name"
```

**A `curl` returning 200 does not prove the screen renders.** Several bugs in
this project's history were client-side only — a hooks-order crash, missing
columns, a wrong default sort — while every API call returned 200. Verify UI
changes in a browser.

## Environment

`.env` is not tracked; copy `.env.example`. `FERNET_KEY` encrypts stored
Amazon refresh tokens at rest — **rotating it invalidates every stored token
and forces OAuth to be re-run**, so it cannot be rotated casually.

Key settings live in `backend/app/config.py`:
`amazon_write_enabled` (default `False`), `sync_schedule_hours` (6),
`amazon_report_poll_max_attempts` (1440 × 10s = 4h — the old 180-attempt
ceiling silently abandoned every ad-group and keyword report),
`sync_stale_after_hours` (24), `alert_webhook_url` (unset means failures are
logged and nobody is notified).

## Further reading

- `docs/HANDOVER.md` — every bug found and fixed, with the evidence. Read
  this before concluding something is broken; it may be a known, fixed issue.
- `docs/DEPLOYMENT.md` — VPS deployment, secret rotation ordering, backups.
- `docs/superpowers/plans/` — the implementation plans, including the
  write-path design and its safety rationale.
