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
docker compose exec api alembic heads      # current: 023
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
mutate Amazon**, and it exposes exactly six operations: keyword bid, target
bid, create negative keyword, campaign daily budget, campaign state
(pause/enable — dayparting only), and campaign placement bid adjustments.

There is no create and no delete anywhere in the app.
`scripts/create_test_campaign.py` is deliberately a standalone script outside
the app so the write client can never gain that capability. `ARCHIVED` is
refused by `update_campaign_state` before the kill-switch is even consulted,
because Amazon cannot un-archive a campaign.

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
| `reconcile_dayparting` | 60min | `dayparting_interval_minutes` |
| `send_daily_digest` | 24h | `digest_interval_hours` |

**`docker compose restart` does not re-read `.env`.** It restarts the
container with the environment it was created with, so a changed setting
appears in the file, in `settings` when you import it via `exec`, and *not* in
the running process — three signals that disagree. Use `docker compose up -d`
to recreate the container. Verify with `docker compose exec api printenv | grep VAR`,
which shows what the process actually has.

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

### Dayparting reconciles; it does not fire on edges

`modules/dayparting/` is the only feature that changes the account without a
human approving each occurrence, so its design is deliberate:

- An entry describes the state a campaign **should be in** during a window, not
  an event at the window's edges. The executor asks "what should this be right
  now?" hourly and corrects drift. Edge triggers would be simpler and wrong —
  this host sleeps, and a missed 6pm "enable" would leave ads off indefinitely.
- Outside every window, campaigns are **left alone**, never force-enabled.
  Otherwise activating a schedule would switch on campaigns a human paused.
- Overlapping windows resolve to `pause`. Overlap is a config error and "off"
  is the cheaper reading.
- Amazon exposes **no hourly performance data** for Sponsored Products
  (`timeUnit: HOURLY` → 400). The operator picks the hours; the app cannot
  recommend them. Do not add a heuristic that implies otherwise.
- Schedules are created inactive. Activation is a separate endpoint so the
  audit trail records who accepted the unattended behaviour.

**Bid windows must derive from a stored baseline, never from the current bid.**
`action_type` is `pause | enable | decrease_bid | increase_bid`. Because the
executor reconciles hourly, applying "−20%" to whatever the bid happens to be
compounds — $0.50 → 0.40 → 0.32 → 0.26 within one day, then lower again
tomorrow. `dayparting_bid_state` stores `baseline_bid` so the answer is always
`baseline × (1 ± pct)`, clamped by the entry's `min_bid`/`max_bid` and then by
Amazon's `AMAZON_MIN_BID`. Outside every bid window the baseline is restored,
which is why `reconcile_schedule` must **not** return early when
`desired_state_at` is None — a bid-only schedule has no desired state at any
hour, and returning would leave the discount in place forever.

Three further traps in that code:

- **A rejected write must not update `last_written_bid`.** Drift detection
  compares Amazon's bid against what the app last wrote, so recording a write
  Amazon refused makes the next run see a phantom manual edit and release a
  keyword nobody touched — with a notification blaming the team.
- **Amazon has no hourly bid multiplier**, so a bid window is written per
  keyword. This account has 222,384 targets. `dayparting_max_bid_writes_per_run`
  caps it, only enabled campaigns and enabled keywords are touched, and the bid
  pass is skipped entirely while the schedule wants a pause. Anything the cap
  drops is logged and recorded on the run — never silently truncated.
- **`bid_adjust` from migration 017** is still allowed by the CHECK constraint
  because rows may exist, but the API rejects it and the UI drops it. Do not
  revive it; it has no executor.

### Adding a rule type touches five places

Rule types are `negative | harvest | bid | budget | placement`. Adding one means
all of:

1. `RuleEngine.execute` — a branch selecting the data source
2. A `_<type>_rows` method shaping rows like every other rule row
3. A `_make_<type>_suggestion` method
4. `ExecutionService.execute` — a branch, plus the write itself
5. **`SUGGESTION_TYPES` in `frontend/app/rules/page.tsx`**

Step 5 is the one that gets missed. Budget rules shipped complete on the backend,
tested, and verified against live data — and were **unreachable**, because the
Rule Type `<select>` had three hardcoded options. The picker is now derived from
`SUGGESTION_TYPES` so this cannot recur, but the general lesson stands: verifying
the engine is not verifying the feature.

### Placement adjustments: points, and wholesale replacement

Two traps specific to `placement` rules:

- Amazon's placement setting is a **percentage uplift, 0–900**, and every
  campaign starts at 0. Changes are in percentage **points** — a multiplicative
  rule applied to 0 stays 0 forever.
- Amazon **replaces the whole `placementBidding` array**. Sending only the
  placement you are changing silently resets the other two to 0%, which looks
  like success. Suggestions therefore store every current adjustment
  (`current_value.all_adjustments`) and execution sends the full set, after
  re-reading live values and refusing if they drifted.

### ACoS units differ between repositories

`SearchTermRepository` and `PerformanceRepository.placement_summary` return ACoS
as a **ratio** (0.577). `PerformanceRepository.get_all_campaigns_summary` returns
a **percentage** (57.7) — while returning CTR as a ratio in the same function.
Rule rows must carry the ratio, because `_field_value` multiplies percent fields
by 100 to compare against the operator's "40" meaning 40%.

Getting this wrong is not cosmetic: feeding the percentage through unconverted
made "cut budget above 40% ACoS" fire at 0.4%, and it proposed cutting a
campaign running at 24%.

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

**The `/backend` proxy destination is fixed at image build time.** Next
evaluates `rewrites()` during `npm run build` and writes the result into
`.next/routes-manifest.json`; `npm run start` reads that file and never
re-runs the config. So `API_URL` must be a **build arg** — setting it only in
the compose `environment:` block changes what the process sees and not what it
routes to. When it was missing at build time the `http://localhost:8000`
fallback got baked in, and every `/backend/*` call returned 500 while the API
was healthy and logged no request at all. Check the built image with:

```bash
docker compose exec frontend grep -o 'http://[a-z0-9.:]*8000' .next/routes-manifest.json
```

It must print `http://api:8000`. Changing `API_URL` requires
`docker compose build frontend`, not a restart.

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
