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

## Known limitation: syncs cannot be driven from the UI

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

## Recommended order of work

1. **Review and merge `fix/sync-honesty`.** Plan 2's Task 4 deletes code from
   this repo, so review this first.
2. **Fix the ASIN harvest bug** (~1 hour). Small, and it affects most of the
   suggestions the engine currently produces.
3. **Plan 2** — background worker, job persistence, scheduler (3–5 days).
4. **Then deploy to a VPS.** Pre-deployment hardening is Task 7 of Plan 2:
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
