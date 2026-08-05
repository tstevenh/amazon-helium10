# Verification Results — Sync Honesty & Resilience

Measured against the live Amazon Ads account
`85e0e890-6baf-45ef-b8de-026c07f050e0` on 2026-08-05.

Plan: [2026-08-05-sync-honesty-and-resilience.md](2026-08-05-sync-honesty-and-resilience.md)

## Structure sync — before vs after

| Table | Before (2026-08-04) | After (2026-08-05) | Change |
|---|---|---|---|
| campaigns | 267 | **289** | +22 (CA profile recovered) |
| ad_groups | 1,385 | **1,422** | +37 (previously `skipped=37`) |
| **targets (keywords)** | **16,680** | **231,798** | **+215,118** |

`231,798` matches the team's own recorded inventory figure exactly.

Per-profile target breakdown after the fix:

| Profile | Country | Targets |
|---|---|---|
| `89389798686160` | US | 222,383 |
| `1043372500031905` | CA | 9,415 |
| `447887639413010` | MX | 0 (genuinely empty) |

Target sync wall time: **4 min 46 s**, 239 pages, `errors: []`, `partial: false`.

## What actually caused the recovery

Being precise about attribution, because it matters for what is and isn't proven:

1. **CA profile's 22 campaigns synced.** The HTTP 502 seen on 2026-08-04 was
   **intermittent, not a permissions problem.** It succeeded on retry the next
   day with no Amazon-side change. The earlier recommendation to open an Amazon
   support case is withdrawn.
2. **The cascade unblocked.** With CA campaigns present, its 37 ad groups and
   9,415 keywords — all previously discarded as `skipped` because their parents
   were missing — now persist.
3. **No connection drop occurred this run.** `grep` for retry activity found
   **zero** retries fired. So the 215k recovery is attributable to (1) and (2)
   plus a clean network run — **not** to retry logic activating.

**Therefore:** the retry protection is proven by unit tests
(`test_amazon_ads_retry.py`, 4 tests including a simulated
`RemoteDisconnected` and an HTTP 502), but has **not** yet been exercised
against a live connection drop. It is insurance, not yet a demonstrated save.

## Honesty fixes — verified behaviour

| Change | Verification |
|---|---|
| `list_campaigns` / `list_ad_groups` / `list_targets` raise `PartialFetchError` | 7 unit tests |
| Partial rows preserved rather than discarded | `test_partial_fetch_error_preserves_successful_items` |
| Soft-delete skipped on partial data | `test_soft_delete_is_guarded_against_partial_data` |
| Sync responses expose `errors[]` and `partial` | Live: all three sync endpoints now return both fields |
| Transient errors retried, 4xx not retried | 4 unit tests |
| Poll ceiling configurable, ≥ 2 h | 4 unit tests |

Total: **19 tests, all passing.** The project had zero tests before this work.

## Report poll ceiling — the measured problem

Amazon report generation times for the *identical* 2-day campaign report on
profile `89389798686160`:

| Run | Duration | Polls | Outcome |
|---|---|---|---|
| 2026-08-04 ~10:02 | ~23 min | 140 | completed |
| 2026-08-04 ~12:44 | **40 min** | **173 / 180** | completed — 4% margin |
| 2026-08-04 13:24 (ad group) | > 40 min | hit 180 | **abandoned** |
| 2026-08-04 14:11 (keyword) | > 40 min | hit 180 | **abandoned** |

A 74% swing on an identical request confirms the latency is Amazon's queue,
not account size and not throttling — no HTTP 429 was ever observed.

The old ceiling was 180 polls ≈ 40 min wall clock. Ad-group and keyword
reports exceeded it **every time**, meaning keyword-level performance data had
**never once been fetched successfully** in the project's history. The API
nonetheless returned `HTTP 200 "Performance sync complete"`.

New default: 1,440 polls × 10 s = **4 hours**, configurable via
`AMAZON_REPORT_POLL_MAX_ATTEMPTS`.

## Performance sync — status

A 2-day performance sync was running when this document was written. The
result determines whether `ad_group_rows` and `target_rows` become non-zero
for the first time. Baseline before the run:

| Table | Rows |
|---|---|
| campaign_performance_daily | 10 |
| ad_group_performance_daily | **0** |
| target_performance_daily | **0** |

*(Section to be completed with the outcome.)*

## Known remaining limitation

The 4-hour ceiling only pays off fully once sync runs in a background worker.
A 2-day sync takes ~2 hours of wall clock; the Next.js proxy times out at 120
seconds. The server now finishes the work and persists the rows, but no
browser can watch it happen. That is Plan 2:

- Background worker (Redis + ARQ/Celery) replacing the `threading.Thread` in `campaigns/router.py`
- Wire the existing unused `sync_jobs` table; delete the in-memory `_sync_jobs` dict
- Frontend polls job status
- Scheduler for periodic syncs
- Pre-VPS hardening: rotate secrets, bind ports to `127.0.0.1`, change `ChangeMe123!`, production frontend build
