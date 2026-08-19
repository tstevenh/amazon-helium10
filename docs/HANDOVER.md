# PPC OS — Handover Notes

**Date:** 2026-08-05
**Branch:** `fix/sync-honesty` (9 commits, not merged)
**Verified against:** live Amazon Ads account `85e0e890-6baf-45ef-b8de-026c07f050e0` (US / CA / MX profiles)

---

## TL;DR

The app was never fundamentally broken. Three bugs stacked up so that
failures were invisible; all three are now fixed and verified against real
Amazon data. **One significant gap remains: the Amazon Search Term report
was never implemented, which silently disables three UI modules.**

---

## What now works, measured

| Data | Before | After |
|---|---|---|
| Campaigns | 267 | **289** |
| Ad groups | 1,385 | **1,422** |
| Keywords / targets | 16,680 | **231,798** |
| Campaign performance rows | 10 | **178** |
| Ad group performance rows | **0** | **1,068** |
| Keyword performance rows | **0** | **935** |

30-day window (2026-07-06 → 2026-08-04), real figures from the live account:

- 15,125 impressions, 124 clicks, **$43.17 spend, 9 orders, $152.05 sales**
- `[AUTO] FBA DRINKWARE` — 87 clicks, $29.50 spend, 8 orders, $137.06 sales, **21.5% ACOS**
- `[SP-PB] FBA DRINKWARE` — 21 clicks, $8.26 spend, 1 order, $14.99 sales, **55.1% ACOS**

`231,798` matches the inventory figure recorded in the original build session
exactly. Ad-group and keyword performance had **never once** been non-zero
before 2026-08-05.

**Conversion columns are confirmed working.** Earlier all-zero `orders`/`sales`
were a genuine reflection of a 2-day window containing 1 click, not a bug.

---

## The three bugs that were fixed

### 1. Missing `date` column — found by the team on 2026-08-03, never tested

Amazon's SP Reporting v3 API only returns columns you explicitly request.
`date` was not in the request, so every row came back with `date = None` and
the `NOT NULL` constraint rejected **100%** of performance upserts. 524
campaign rows, 4,129 ad group rows, every keyword row — all refused.

The fix was applied on 2026-08-03 and verified only with `grep`. The Docker
environment then broke and the project was handed over, so the fix had never
been executed. It works.

### 2. Report poll ceiling too short — 40 minutes

`_POLL_MAX_ATTEMPTS = 180` at 10-second intervals ≈ 40 minutes wall clock.
Measured report generation times on this account:

| Request | Duration | Outcome |
|---|---|---|
| 2-day campaign | 23 min (140 polls) | completed |
| 2-day campaign (same request, later) | **40 min (173/180 polls)** | completed — 4% margin |
| 2-day ad group | > 40 min | **abandoned** |
| 2-day keyword | > 40 min | **abandoned** |

A 74% swing on an identical request proves the latency is **Amazon's queue**,
not account size and not throttling — no HTTP 429 was ever observed. The
account is not limited and there is no speed tier to buy.

Ad-group and keyword reports exceeded the ceiling **every time**, meaning that
data had never been fetched successfully in the project's history. The API
nonetheless returned `HTTP 200 "Performance sync complete"`.

Ceiling is now configurable, default 1,440 polls × 10 s = **4 hours**.

### 3. Failures reported as successes

Every Amazon fetch failure was caught, logged at `warning`, and returned as an
empty list. A total auth failure and an empty account were indistinguishable.
This is why the problem resisted diagnosis for a month — the evidence existed
only in container logs nobody was reading.

Concretely, on 2026-08-04: Amazon dropped the connection part-way through ~230
sequential keyword page requests. **215,118 keywords were lost** and the API
returned `200 OK, "Target sync complete"`.

Now: `PartialFetchError` carries both the rows that succeeded and a
description of each failure. All sync endpoints return `errors[]` and
`partial`. Retry with exponential backoff was added for transport errors and
HTTP 429/5xx (4xx is deliberately not retried).

**Critical safety guard:** soft-delete is now skipped on a partial fetch.
Rows absent from an incomplete fetch were not deleted on Amazon — they simply
weren't retrieved — and deleting them would destroy live campaign data.

---

## ✅ RESOLVED 2026-08-05: Search Terms now implemented

The gap described below was **fixed and verified** after the first draft of
these notes. `fetch_search_term_performance()` was added using report type
`spSearchTerm` / `groupBy: ["searchTerm"]`, and `_sync_profile` was split into
real and mock paths.

Verified against the live account (30-day window, 15 min 26 s):

```
"terms_synced": 121, "suggestions_generated": 9, "errors": []
```

- 121 rows, 106 distinct search terms, 2026-07-06 → 2026-08-04
- Real customer queries: `sobriety gifts for women`, `boss mug`,
  `chief engineer cup`, `microbiology mug`, plus ASIN placements
- **The suggestions engine ran automatically and produced 9 harvest
  candidates** with real reasoning, e.g. *"Strong sales $14.99 with ACOS 3.0%
  — add as Exact"*

**All three previously blocked modules — Search Terms, Suggestions, Rules —
are now operational.**

A latent bug was fixed along the way: `_request_report` chose `groupBy` with a
chained conditional ending in `else ["targeting"]`, so any unrecognised report
type silently received the wrong grouping and would have returned a
plausible-looking but incorrect report. It now raises on an unmapped type.

### ⚠️ Follow-up: the harvest engine mishandles ASIN search terms

7 of the 9 generated suggestions are ASINs (`b0fcs8jvp9`, `b07gn4jsx1`, …)
recommended as `keyword_exact`. ASINs come from product-targeting placements,
not text queries — **an ASIN cannot be added as an exact-match keyword in
Amazon.** Those suggestions are not actionable.

This is a pre-existing flaw in `suggestions/service.py`, not a regression. It
was invisible until search terms populated. The fix is an ASIN-pattern check
(`^b0[a-z0-9]{8}$`, case-insensitive) routing those terms to a product-target
suggestion type instead of `keyword_exact`. Small, but it affects the majority
of current suggestions.

---

## Original finding (now fixed — kept for context)

### Search Terms was a mock-only stub

`backend/app/modules/search_terms/service.py:104`

```python
if not settings.amazon_mock_mode:
    logger.warning("Real Amazon Search Term API not implemented; skipping profile %s", profile.id)
    return 0
```

The real Amazon Search Term report was **never implemented**. The function only
generates hardcoded mock fixtures. In real mode it returns 0.

This is not a bug — it is an unbuilt feature that **looks** built. The endpoint
exists, returns `HTTP 200`, reports `"Search terms sync-all completed"`, and
the UI has a complete Search Terms page with date/ACOS/spend filters and a
Sync button. Nothing signals the implementation is absent.

### It disables two more modules

Both engines read **only** from search terms:

- `suggestions/service.py:160` — `st_repo.get_aggregated_by_term(...)`
- `rules/service.py:141` — same call

Empty search terms ⇒ both evaluate zero rows and generate zero suggestions,
silently and permanently.

### Module status in real mode

| Module | Status before 2026-08-05 | Status now |
|---|---|---|
| Campaign Manager | ✅ working | ✅ working |
| Ad Groups | ✅ working | ✅ working |
| Keywords | ✅ working | ✅ working |
| Dashboard | labelled "Soon" | still not built |
| **Search Terms** | ❌ mock-only stub | ✅ **working** |
| **Suggestions** | ❌ blocked | ✅ **working** (see ASIN caveat) |
| **Rules** | ❌ blocked | ✅ **unblocked** — has data to evaluate |

### How to fix it

The plumbing already exists. Amazon's search-term data comes from the same
async Reporting API that now works for the other three levels — report type
`spSearchTerm` with `searchTerm` in the columns list. It needs:

1. `fetch_search_term_performance()` in `app/core/amazon_reporting.py`,
   alongside the three existing fetchers. Copy their shape; remember `"date"`
   must be in the columns list (see bug 1).
2. `_sync_profile()` in `search_terms/service.py` rewritten to call it and
   upsert real rows instead of fixtures.

Roughly a day. It unblocks three modules at once, and is the highest-value
remaining work.

---

## Also worth knowing

**The CA profile's HTTP 502 was intermittent, not a permissions problem.** It
failed on 2026-08-04 and succeeded on 2026-08-05 with no Amazon-side change.
No support case needed. Retry now covers it. Its 22 campaigns, 37 ad groups
and 9,415 keywords — all previously discarded as `skipped` because their
parents were missing — now sync.

**The MX profile is genuinely empty** — 0 campaigns, no error.

**Nothing in this app can modify your Amazon account.** Audited: zero
`requests.put`, `requests.patch` or `requests.delete` anywhere in the backend.
The only public functions in the Amazon client are `list_*` plus auth. The
rules engine's own docstring: *"Creates Suggestions only — never touches
Amazon Ads."* This matches the team's stated constraint and is a deliberate
design decision, not an oversight. Note it also means the app does **not**
push bid changes back to Amazon the way Helium 10's Adtomic does.

**The 2026-08-03 Docker failure was not a code bug.** Postgres had been killed
uncleanly and performed WAL crash recovery (50+ seconds of fsync), which blew
Docker's healthcheck so `api` and `frontend` never started. Waiting it out was
the whole fix.

---

## What changed in the codebase

9 commits on `fix/sync-honesty`, starting from a baseline commit of the code
exactly as received, so every change is a reviewable diff.

Two things the project did not have before and now does:

- **Version control.** `.gitignore` excludes `.env` — it contains the live
  `AMAZON_CLIENT_SECRET`, `FERNET_KEY` and `JWT_SECRET_KEY`.
- **Tests.** 19, run with `docker compose exec api python -m pytest tests -q`.

Files changed: `app/core/amazon_ads.py`, `app/core/amazon_reporting.py`,
`app/config.py`, `app/modules/campaigns/service.py`, plus new
`backend/tests/`, `backend/pytest.ini`, and a `tests/` mount in
`docker-compose.yml`.

---

## ✅ RESOLVED 2026-08-05: Plan 2 complete — background worker, scheduler, alerting

The limitation described below was **fixed**. All 10 Plan 2 tasks are done on
branch `feat/background-worker` (11 commits, 80 tests passing).

| | Before | After |
|---|---|---|
| `POST /sync-all` response time | held ~51 min | **202 + job_id in 17 ms** |
| Job state after container restart | `{}` — forgotten | **full state intact** |
| Concurrency guard | per-process memory | **database; survives restarts** |
| Automatic sync | none | **every 6 hours (Celery Beat)** |
| Failure alerting | none | **every 30 min + `/health/sync`** |
| Report patience ceiling | 40 min | **4 hours (configurable)** |
| Published ports | `0.0.0.0` with `ChangeMe123!` | **`127.0.0.1` only** |
| Frontend container | `npm run dev` | **production build** |
| Backups | none | **`scripts/backup-db.sh`, restore-tested** |

New services: `redis` (broker), `worker` (Celery), `beat` (scheduler).
Migrations `012` and `013` applied; alembic head is now `013`.

### Two bugs found while verifying, not predicted by the plan

**The `sync_jobs` table already had check constraints** on `status` and
`job_type` that a truncated `\d` output had hidden. Unit tests passed while a
real insert raised `CheckViolation`. Caught only by smoke-testing against the
live database. Consequences:

- The correct status vocabulary is `queued | running | success | failed |
  partial` — not the `completed` the plan assumed.
- **The original authors had included a `partial` status**, which maps exactly
  onto Plan 1's `errors[]` contract. `mark_completed` now downgrades to
  `partial` rather than recording an incomplete sync as a success. Their idea,
  and better than what had been designed.
- Migration `013` widens `ck_sync_jobs_job_type` to allow `sync_all`; the
  original constraint enumerated one value per sync *level*.

**The rules engine reintroduced the ASIN bug.** Verifying it (P2-10) showed 2
of its 10 suggestions were `negative_exact` for ASINs. It has its own
`_make_suggestion`, so the earlier fix in `SuggestionEngine` never covered it.
The pattern and mapping now live in `suggestions/asin.py`, imported by both
engines, so the two paths cannot drift apart again — which is exactly how the
bug survived the first fix.

### Rules engine: verified executing for the first time

`rows_evaluated=106`, `suggestions_generated=10`, completed in 20 ms. It had
never been run in the project's history. After the ASIN fix it emits
`negative_product_target` for the 2 ASIN terms and `negative_exact` for the 8
genuine queries — **0 bad rows across both engines**.

### Also fixed: the frontend did not typecheck

`next build` type-checks by default, so 8 pre-existing TypeScript errors would
have blocked the production image entirely. Both causes were real:

- `ErrorState` declared a prop `error` while all 7 call sites passed
  `message`, so **actual error text was silently dropped** and users only ever
  saw the generic "Something went wrong". Fittingly on-theme.
- `hooks/useApi.ts` read a `token` field `AuthContextValue` does not have. It
  was never imported anywhere — deleted as dead code.

Frontend: 8 errors → 0. The account detail page needed **no changes** — it
already polled `sync-status` and reads `sync_job.running/.error/.result`, all
of which the backend change preserved.

### Still outstanding — needs a human, not a developer

**Secrets are not rotated.** `FERNET_KEY` encrypts the stored Amazon refresh
tokens, so rotating it forces OAuth to be re-run and needs someone with the
Amazon login present. `docs/DEPLOYMENT.md` has the required ordering. Do this
before deploying — the current values sat in a `Downloads` folder in plaintext.

**No alert webhook is configured.** `ALERT_WEBHOOK_URL` is empty, so alerts
log at `ERROR` rather than reaching anyone. Set it to a Slack or Discord
incoming webhook in production; no code change needed.

---

## Original limitation (now fixed — kept for context)

### Syncs could not be driven from the UI

The 4-hour poll ceiling means the server now completes work no browser can
watch. A 30-day sync takes **51 minutes**; the Next.js proxy times out at 20
minutes and the browser's own fetch at 2. The server finishes and persists the
rows regardless — but today a sync must be triggered with `curl`, not by
clicking a button.

**This is the single thing standing between the app and daily usability**, and
it is fully specified in
`docs/superpowers/plans/2026-08-05-background-worker-and-scheduler.md`
(Plan 2): a Celery worker, the already-existing-but-unused `sync_jobs` table
wired up, and a Beat schedule. 3–5 days, one new dependency (Redis).

Two things Plan 2 also fixes:

- Job state currently lives in an in-memory dict, so a container restart
  forgets a running sync, and with multiple API workers two people could start
  the same sync without seeing each other's. **This gets actively worse on a
  shared server, so Plan 2 should land before any VPS deployment.**
- Nothing syncs automatically. Data is only as fresh as the last manual run.

---

## ✅ 2026-08-06: V1 feature-complete except the gated live write

Plans 3 and 4 are done. 32 commits on `feat/background-worker`, 134 tests.

### The V1 loop now exists end to end

| Spec workflow | Status |
|---|---|
| 1. Connect account → sync | ✅ |
| 2. Browse live performance data | ✅ |
| 3. Create a Bid Rule scoped to campaigns | ✅ |
| 4. Daily job evaluates rules → suggestions | ✅ every 24 h |
| 5. Inbox approve / reject / bulk | ✅ |
| 6. Execution writes to Amazon | ✅ built, ⛔ never fired at a real bid |
| 7. Logs show who/what/when/old→new | ✅ with an Undo button |

All 7 V1 pages exist. Beat runs three schedules: sync 6 h, rules 24 h,
health 30 min.

### Safety model for writes

`AMAZON_WRITE_ENABLED` defaults to **false** — with it off the write client
raises before a request is even built. Three endpoints only (keyword bid,
target bid, negative keyword); a test fails if anyone adds campaign creation.
Every attempt is recorded in `suggestion_actions` *before* the call. A failed
call writes no `change_log` row, because a row there means "this really
changed". Rollback exists and was built before the first write, not after.

Proven: the app created a paused test campaign on the live account
(`153113201181536`) and read it back. **Changing an existing bid and undoing
it is still unproven** — that is the one remaining step.

### Bid suggestions are now executable

A bid suggestion carries `target_id`, `current_value` and `suggested_value`.
Without those the execution job had nothing to act on, which is why execution
was impossible before. Verified live: 105 rows evaluated → 4 suggestions,
each with a real target and bid change ($0.40 → $0.34).

### Two field bugs fixed

**Empty states lied.** A restored `localStorage` selection of MX — the only
marketplace with zero campaigns — made every page say "Run Sync All to pull
data". Two people concluded the app was broken. It now says "MX has no
campaigns. US has 268, CA has 22." with a switch button.

**Scheduled syncs would have hammered Amazon forever.** `force_full=True` was
ported faithfully from the old daemon thread, where it was harmless because
nothing ran on a schedule. With Beat it forced a 6–12 hour 90-day pull every
6 hours. Now a 3-day rolling window, which is also exactly what the team
asked for independently.

---

## ✅ 2026-08-12: Dashboard pass for non-engineering users

Everything below was found by clicking through the app in a browser rather
than by reading code or calling the API. Each one made the app look broken to
someone who did not build it.

| What the user saw | What was actually wrong |
|---|---|
| Ad Groups and Keywords showed names and bids but no money columns | The metric columns only ever existed on the Campaigns page. Added `GET /performance/ad-groups` and `GET /performance/targets`, plus `components/ui/metricColumns.tsx` so all three screens format numbers the same way. |
| Keywords looked like a list of dead keywords | The list applied `LIMIT 2000` with **no `ORDER BY`**, so the rows shown were an arbitrary slice of 219,285 — almost all zero-traffic. Now ranked by spend in SQL. |
| "Showing first 2,000 — use the search box to find the rest" | Untrue: search only filters rows already loaded. Now reads "top 2,000 by spend, out of 219,285". |
| Rules said "No rules yet" despite two enabled rules | With the header on **All Profiles** the page silently queried whichever profile sorted first. Now loads every profile in the account and shows a Marketplace column; the create modal asks which marketplace instead of guessing. |
| Campaign Manager opened on paused campaigns with dashes | No default sort. `DataTable` gained `defaultSortCol`/`defaultSortDir`; the three data screens default to Spend ↓. |
| Sorting by any money column gave nonsense order | Numeric values arrive from the API as **strings**, so `<`/`>` compared them alphabetically — `$8.97` ranked above `$27.71`. `DataTable` now coerces before comparing. This affected every numeric column app-wide. |
| Suggestions said "AI-generated" | They come from threshold rules the team can read and edit. Subtitle now says so. |

**Worth telling whoever uses this:** in the last 30 days only **17 of the US
profile's 219,285 keywords spent anything at all**. That is the account, not a
sync failure — most keywords sit in paused or low-budget campaigns. Ranking by
spend is what makes that legible instead of alarming.

Guarded by `backend/tests/modules/test_perf_ranking.py` (8 tests), including
the invariant that `LIMIT` must never appear without `ORDER BY`.

---

## ✅ 2026-08-12 (later): every remaining spec feature built

The instruction was to build everything both spec documents require before
deploying. That is now done, with two exceptions that cannot be built — see
below.

| Feature | Spec | State |
|---|---|---|
| Rule Templates | Part 21.2 | 4 vetted built-ins, seeded on API startup |
| Notifications + daily digest | §8.9, §4.3 | Log-first, so an unconfigured webhook still leaves a record |
| Budget Rules | Phase 2 | 3-day grace window, $1.00 floor, drift check on execute |
| Dayparting | §8.7, §13.7 | Manual hours, hourly reconciliation, schedules start stopped |
| Keyword Intelligence v1 | Part 17 | Cerebro import, snapshot history, trends |
| Placement data + screen | §8 | 219 rows on the live account |
| Anomaly detection | §13.1 | Query-time; found a real problem immediately |
| Placement Rules | Phase 3 | Percentage points, full-array writes |
| Opportunity Finder | §17.5 | All 5 patterns, gated on ≥3 snapshots |
| Competitor Comparison | Phase 3 | Keyword gap between two ASINs |

Six Amazon write operations now exist, all behind `AMAZON_WRITE_ENABLED`:
keyword bid, target bid, negative keyword, campaign budget, campaign state
(dayparting only), placement bid adjustments. Still no create, no delete, and
`ARCHIVED` is refused outright.

Schema at migration **022**. Test suite at **290**.

### Two things cannot be built

**Hourly dayparting recommendations.** Amazon does not expose hourly
performance for Sponsored Products. Probed three ways on 2026-08-12:
`timeUnit: HOURLY` → *"not supported for this report type"*; a `startDateTime`
column → *"invalid values"*; an hour column without `timeUnit` → *"required
fields missing"*. The spec half-admits this in §7.2 ("not available faster than
daily aggregation") while the dayparting section asks for hour-of-day history.
The operator therefore picks the hours; the app does not suggest them.

**Anything needing organic rank.** `Helium10_Merged` names rank as H10's real
moat; `PPC_OS_Merged` cancels the Keyword Tracker outright — *"NEVER — REMOVED
— Decision 2. Not deferred, formally cancelled."* Confirmed still cancelled by
the user's team on 2026-08-12. So the rank-enriched Search Terms tab and
Keyword Tracker rules are out by decision, not oversight. This is also the
reason to keep the Helium 10 subscription: §17.6 says keep it until Keyword
Intelligence has 3–6 months of snapshots.

### Bugs found the same day, several self-inflicted

| Bug | Why it mattered |
|---|---|
| ACoS off by 100× in budget rules | "Cut budget above 40% ACoS" evaluated as 0.4% and proposed cutting a campaign running at 24%. Two repositories disagree on ratio vs percentage — see CLAUDE.md |
| Scheduled rule evaluation saved nothing | Logged "succeeded" for a week. `RuleEngine` only flushes; the Celery task never committed |
| `Campaign.placement_bidding` missing from the model | Migration added the column, the ORM did not. Endpoint returned 200 *because* there were no rows yet, so the failing line never ran |
| Amazon HTTP 425 treated as failure | Amazon dedupes report requests. Any retry inside the 20–40 min window reported an error while the report was building |
| change-log `count` was the page size | Dashboard fetched 1 row to be cheap and reported "1 change" out of 2 |
| Empty `placementClassification` silently bucketed | 44 of 219 rows arrived unlabelled; only non-empty mismatches were logged |

### Three features shipped unreachable

Worth recording as a pattern, not just incidents. In each case the backend was
complete, tested, and verified against live data — and the screen was not:

- **Budget rules** — the Rule Type `<select>` had three hardcoded options and
  never gained `budget`. Verified via Python, so the gap survived a "done"
  claim. The picker is now derived from the rule-type map.
- **Placements** — data, write operation and endpoint built; no screen.
- **Competitor Comparison** — endpoint built; nothing called it.

All three were found by a direct question about whether the *dashboard* had
been verified, not by any test. The rule that follows: **verifying the engine
is not verifying the feature.**


## ✅ 2026-08-19: dayparting bid writes proven against the live account

`AMAZON_WRITE_ENABLED` was turned on deliberately, scoped to one campaign
(`ZZ-API-TEST-DO-NOT-USE`, one exact-match keyword `zzapitestdonotuse` with no
realistic search volume), and turned off again afterwards. Every assertion below
was read back **from Amazon**, not from our own database — the local mirror
agreeing with itself proves nothing.

Baseline read from Amazon first: `bid=0.75`, `state=ENABLED`.

| What was tested | Result |
|---|---|
| Campaign state write (`PAUSED` → `ENABLED`) | Amazon confirmed |
| Dayparting bid write, `decrease_bid 20%` | Amazon reported **0.60** = 0.75 × 0.80 |
| **Re-running the same window** | Amazon still **0.60**, `changed: 0` — no compounding, no wasted write |
| No bid window active | Amazon reported **0.75** — baseline restored |
| A bid changed outside the app (set to 0.99 directly) | Amazon kept **0.99**; the target was released and a `dayparting_released` notification recorded |

The third row is the one that mattered. Reconciliation re-asserts the desired
state hourly, so an implementation that applied "−20%" to the *current* bid
would have produced 0.48 on the second run and roughly 0.17 by end of day. It
produced 0.60 both times, which is what the stored baseline is for.

The fifth row is the safety property: the app did not overwrite a human. The
release reason it recorded reads *"bid is 0.99 but this schedule last wrote 0.60
— changed outside the app, so the schedule stopped managing it"*.

Audit trail written as designed: `change_log` gained one `target`/`bid`
`0.75 → 0.60` row with `source=dayparting`, `dayparting_bid_state` held
`baseline_bid=0.75, last_written_bid=0.60`, and `dayparting_runs` recorded
`applied` with a readable explanation.

**Restored afterwards, and verified from Amazon:** bid back to `0.75`, campaign
back to `paused`, temporary schedule deleted, `dayparting_bid_state` empty,
`AMAZON_WRITE_ENABLED=false` confirmed in the running process (not merely in
`.env` — `docker compose restart` would not have reloaded it).

Caveat worth keeping in mind: this proved **one** keyword. It did not exercise
the per-run write cap, partial failures across many keywords, or Amazon's
rate limits, all of which only appear at scale. Enable a bid window on a real
campaign with a small keyword count first.

---
### Still unproven, and why

- Only **keyword-bid** writes had ever reached Amazon. **Campaign state and
  dayparting bid writes were proven live on 2026-08-19** (below). Budget and
  placement writes are built, guarded and unit-tested but have never executed
  for real.
- **The Cerebro parser has never seen a real export.** It was verified against
  a deliberately messy file written to look like one. The alias table comes
  from Helium 10's documentation, and the two-step import exists so a header
  change is visible before anything is stored.
- **Opportunity patterns have never run on real data** — no snapshots imported.

---

## Recommended order of work

1. **Review `feat/background-worker`** (11 commits) and `main` (13 commits
   already merged). Plan 2 deleted the threading and in-memory dict your team
   wrote, so that review matters.
2. **Set `ALERT_WEBHOOK_URL`** to a Slack or Discord webhook (~5 minutes). No
   code change; alerting is already built and tested.
3. **Rotate the secrets** following `docs/DEPLOYMENT.md` (~1 hour, needs
   someone with the Amazon login for the `FERNET_KEY` step).
4. **Deploy to a VPS.** Hardening is done; see `docs/DEPLOYMENT.md` for TLS,
   the OAuth redirect change and the backup cron.

### Superseded — kept so the trail is legible

The earlier plan of work was: merge Plan 1, fix the ASIN bug, build Plan 2,
then deploy. Items 2 and 3 of that list are now complete. Pre-deployment
hardening was Task 7 of Plan 2:
   bind ports to `127.0.0.1` (they are currently on `0.0.0.0` with the
   password `ChangeMe123!`), rotate every secret, and give the frontend a
   production build instead of `npm run dev`.

**Rotate the secrets regardless of timeline.** `.env` sat in a `Downloads`
folder in plaintext. Note that rotating `FERNET_KEY` invalidates every stored
Amazon refresh token and forces OAuth to be re-run — see Plan 2 Task 7 for the
required ordering.

---

## Reference

- Plan 1 (executed): `docs/superpowers/plans/2026-08-05-sync-honesty-and-resilience.md`
- Plan 1 results: `docs/superpowers/plans/2026-08-05-verification-results.md`
- Plan 2 (not started): `docs/superpowers/plans/2026-08-05-background-worker-and-scheduler.md`

Useful commands:

```bash
# Start everything
docker compose up -d

# Run the tests
docker compose exec api python -m pytest tests -q

# Row counts at a glance
docker compose exec postgres psql -U ppc_os -d ppc_os -c "SELECT (SELECT count(*) FROM campaigns WHERE deleted_at IS NULL) camp,(SELECT count(*) FROM ad_groups WHERE deleted_at IS NULL) ag,(SELECT count(*) FROM targets WHERE deleted_at IS NULL) tgt,(SELECT count(*) FROM campaign_performance_daily) cperf,(SELECT count(*) FROM ad_group_performance_daily) agperf,(SELECT count(*) FROM target_performance_daily) tperf,(SELECT count(*) FROM search_terms) st;"

# Watch a sync
docker compose logs -f api | grep -vE "GET /health"
```

App login is the seeded dev account in `.env` (`SEED_ADMIN_EMAIL` /
`SEED_ADMIN_PASSWORD`) at http://localhost:3000/login. **Change it before
deploying anywhere.**
