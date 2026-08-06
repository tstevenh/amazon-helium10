# V1 Completion Implementation Plan (Plan 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish V1 as the merged spec defines it — an operator logs in, reviews suggestions, approves one, watches it apply to Amazon, and sees the full who/what/when/old→new trail with an undo button.

**Architecture:** Mostly frontend. The backend work from Plans 1–3 already exposes everything needed: `/change-log`, `/suggestions/{id}/execute`, `/suggestions/{id}/actions`, `/change-log/{id}/rollback`. What remains is wiring those into the UI, adding the bid rule type with per-campaign scoping, and putting rule evaluation on the existing Celery Beat schedule.

**Tech Stack:** Next.js 14 App Router, TypeScript, Tailwind; FastAPI, SQLAlchemy, Celery + Redis, PostgreSQL 16.

## Global Constraints

- **"Mandatory: Rule → Suggestion → Human Review → Apply. NO auto-apply in V1."**
- **"In V1: 'executing' a rule means PRODUCING A SUGGESTION, not writing to Amazon."**
- `AMAZON_WRITE_ENABLED` stays **false** by default. Nothing in this plan changes that.
- Two roles only: Admin, User. Executing and rolling back are Admin-only.
- Do NOT modify historical migrations. Head is `014`; this plan adds `015`.
- The write client stays at three endpoints. No campaign/ad-group creation.

## V1 scorecard — where this plan finishes the job

| Spec page | Status entering Plan 4 |
|---|---|
| Login | ✅ |
| Campaign Manager (+ KPI strip) | ✅ list; KPI strip missing |
| Campaign Detail | ✅ |
| Rules Builder | ⚠️ exists; no bid type, no campaign scoping |
| Suggestions Inbox | ⚠️ approve/reject work; no Execute |
| **Logs** | ❌ not built |
| Settings → Accounts | ✅ |

| Spec workflow | Status |
|---|---|
| 1. Connect account → sync | ✅ |
| 2. Browse live data | ✅ |
| 3. Create Bid Rule scoped to campaigns | ❌ |
| 4. Daily job evaluates → suggestions | ⚠️ engine works, not scheduled |
| 5. Inbox approve/reject/bulk | ✅ |
| 6. Execution writes to Amazon | ⚠️ backend done, no UI |
| 7. Logs show who/what/when/old→new | ❌ |

---

### Task 1: Honest empty states and marketplace guidance

A user re-logged in, `localStorage` restored a saved selection of **MX** — the
only marketplace with zero campaigns — and every page showed "No campaigns
found. Run Sync All from Accounts to pull data."

That advice is wrong and actively harmful: it tells the operator to run an
hour-long sync when the real answer is "switch marketplace". This is the
second time someone has concluded the app was broken when it was not.

**Files:**
- Modify: `frontend/app/campaigns/page.tsx`, `frontend/app/ad-groups/page.tsx`, `frontend/app/keywords/page.tsx`
- Modify: `frontend/context/AccountProfileContext.tsx` — expose per-profile row counts
- Create: `backend/app/modules/accounts/router.py` addition — `GET /accounts/{id}/profile-counts`

**Interfaces:**
- Produces: `GET /accounts/{id}/profile-counts` →
  `[{profile_id, country_code, campaigns, ad_groups, targets}]`
- `useAccountProfile()` gains `profileCounts: Record<string, {campaigns: number}>`

- [ ] **Step 1: Backend — one query for all per-profile counts**

Add to `accounts/router.py`. One grouped query, not one per profile:

```python
@router.get("/{account_id}/profile-counts")
def profile_counts(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> JSONResponse:
    """Row counts per marketplace, so the UI can say WHERE the data is.

    An operator landing on an empty marketplace should be told which one has
    data, not told to run a sync that will change nothing.
    """
    rows = db.execute(_sa_text("""
        SELECT p.id, p.country_code,
               count(DISTINCT c.id) FILTER (WHERE c.deleted_at IS NULL) AS campaigns
        FROM ads_profiles p
        LEFT JOIN campaigns c ON c.profile_id = p.id
        WHERE p.seller_account_id = :aid
        GROUP BY p.id, p.country_code
        ORDER BY 3 DESC
    """), {"aid": str(account_id)}).fetchall()
    return JSONResponse(content=[
        {"profile_id": str(r[0]), "country_code": r[1], "campaigns": int(r[2] or 0)}
        for r in rows
    ])
```

- [ ] **Step 2: Frontend — replace the misleading empty state**

Where a page currently renders "No campaigns found. Run Sync All…", branch on
whether *another* marketplace has data:

```tsx
// Wrong marketplace is far more likely than missing data.
const otherWithData = profileCounts
  .filter(p => p.profile_id !== currentProfileId && p.campaigns > 0)
  .sort((a, b) => b.campaigns - a.campaigns)

if (otherWithData.length > 0) {
  return (
    <EmptyState
      message={
        `${currentCountryCode} has no campaigns. ` +
        otherWithData.map(p => `${p.country_code} has ${p.campaigns}`).join(', ') + '.'
      }
      onRetry={() => setCurrentProfile(otherWithData[0].profile_id)}
    />
  )
}
```

The action button switches marketplace rather than suggesting a sync.

- [ ] **Step 3: Only suggest syncing when nothing anywhere has data**

Keep the original message for the genuine first-run case — every marketplace
empty means the account really has not synced.

- [ ] **Step 4: Verify against the live database**

MX must show "MX has no campaigns. US has 268, CA has 22." with a working
switch button; US must show the table.

- [ ] **Step 5: Commit**

---

### Task 2: Logs screen

The spec calls this "non-negotiable for trust in automation. Must answer 'why
did this bid change' instantly." `change_log` is populated and
`GET /change-log` works; there is no page.

**Files:**
- Create: `frontend/app/logs/page.tsx`
- Modify: `frontend/lib/api.ts`, `frontend/lib/types.ts`, the sidebar nav

**Interfaces:**
- Consumes: `GET /change-log`, `POST /change-log/{id}/rollback`
- Produces: `api.getChangeLog(profileId?)`, `api.rollbackChange(id)`

- [ ] **Step 1: Add the API client methods**

- [ ] **Step 2: Build the table**

Columns: when · marketplace · entity · field · **old → new** · source · who ·
Undo. Rows already rolled back show the timestamp instead of a button.

- [ ] **Step 3: Undo button with confirmation**

Rollback writes to Amazon. Confirm with the actual values —
"Restore bid from $0.85 back to $0.75?" — not a generic "Are you sure?".

- [ ] **Step 4: Add Logs to the sidebar**

- [ ] **Step 5: Verify empty state reads sensibly** (nothing has changed yet)

- [ ] **Step 6: Commit**

---

### Task 3: Execute button on the Suggestions Inbox

**Files:**
- Modify: `frontend/app/suggestions/page.tsx`, `frontend/lib/api.ts`

- [ ] **Step 1: `api.executeSuggestion(id)` and `api.getSuggestionActions(id)`**

- [ ] **Step 2: Execute button, shown only on `approved` rows**

Never on pending — approving and applying stay separate acts, per the spec.

- [ ] **Step 3: Confirmation dialog naming the exact change**

"Change bid on 'ergonomic mouse pad' from $1.20 to $0.80 on Amazon?" The
operator must see what will happen before it happens.

- [ ] **Step 4: Poll `/actions` and show the outcome**

Including the failure case. If `AMAZON_WRITE_ENABLED` is false the
suggestion goes `execution_failed` with a readable reason — the UI must show
that rather than spinning.

- [ ] **Step 5: Commit**

---

### Task 4: Bid rules with per-campaign scoping

Rules currently apply to an entire marketplace and only produce
negatives/harvests. The spec's workflow 3 is "a Bid Rule **scoped to specific
campaigns**".

**Files:**
- Create: `backend/alembic/versions/015_rule_campaign_scope.py`
- Modify: `backend/app/modules/rules/{models,service,schemas,router}.py`
- Modify: `frontend/app/rules/page.tsx`

**Interfaces:**
- Produces: `rule_campaign_scope` table (`rule_id`, `campaign_id`);
  `RuleCreate.campaign_ids: list[uuid] | None` — `None`/empty means the whole
  profile, preserving today's behaviour.

- [ ] **Step 1: Migration 015**

- [ ] **Step 2: Scope filtering in `RuleEngine.execute`**

When a rule has scoped campaigns, evaluate only search terms belonging to
them.

- [ ] **Step 3: Bid suggestion types**

`bid_increase` / `bid_decrease` must populate `target_id`, `current_value`
and `suggested_value` — without those, execution has nothing to act on
(this was the gap that made execution impossible in the first place).

- [ ] **Step 4: Campaign multi-select in the Rule Builder**

- [ ] **Step 5: Verify a scoped bid rule produces an executable suggestion**

`rows_evaluated > 0`, and the suggestion has a `target_id` and a numeric
`suggested_value.bid`.

- [ ] **Step 6: Commit**

---

### Task 5: Scheduled rule evaluation

Rules only run when someone clicks. Spec workflow 4 is "**Daily job**
evaluates the rule against synced data".

**Files:**
- Create: `backend/app/worker/rule_tasks.py`
- Modify: `backend/app/worker/celery_app.py`, `backend/app/config.py`

**Interfaces:**
- Produces: `@celery_app.task(name="evaluate_all_rules")`, setting
  `rule_schedule_hours: int = 24`

- [ ] **Step 1: Fan-out task over enabled rules**

Mirror `enqueue_scheduled_syncs`: iterate enabled rules, evaluate each,
record a `rule_execution` row. Rules never write to Amazon — they only
create suggestions — so no kill-switch interaction.

- [ ] **Step 2: Add to the Beat schedule**

- [ ] **Step 3: Recreate the worker and confirm registration**

Celery reads its task registry only at startup; a missing registration fails
silently with `KeyError`. This has bitten twice.

- [ ] **Step 4: Trigger once manually and confirm suggestions appear**

- [ ] **Step 5: Commit**

---

### Task 6: Sync day picker and Campaign Manager KPI strip

**Files:**
- Modify: `frontend/app/accounts/[id]/page.tsx`, `frontend/app/campaigns/page.tsx`

- [ ] **Step 1: Day selector next to Sync All**

7 / 30 / 90 days, passed as `perf_days`. Default stays "routine" (the 3-day
rolling window), with 90 clearly labelled as a slow backfill.

- [ ] **Step 2: KPI strip above the campaign table**

Total spend, sales, ACOS, ROAS, clicks, orders for the selected window. The
spec says this "replaces a standalone Dashboard for V1".

- [ ] **Step 3: Commit**

---

## Self-Review

**Spec coverage.** Logs page → Task 2. Execution UI → Task 3. Bid rules and
campaign scoping → Task 4. Scheduled evaluation → Task 5. KPI strip → Task 6.
Task 1 is not in the spec; it is a usability bug found in the field that has
now cost two people significant time.

**Ordering.** Task 1 first (smallest, stops the app looking broken). Tasks 2
and 3 are the trust surface and should land together — an Execute button
without a Logs screen and an undo is worse than neither. Tasks 4-6 are
independent.

**Dependencies.** Tasks 2 and 3 need Plan 3's backend, which is complete.
Task 4's bid suggestions are what make Plan 3's `ExecutionService` useful —
until then it can only execute manually-created suggestions.

**Risk.** Task 3 puts a button in the UI that changes a live ad account. It
must not ship before Task 2's undo. The confirmation dialog must name the
actual old and new values, not a generic warning — a dialog nobody reads is
not a safeguard.

## Out of scope — Phase 2 and beyond

Dashboard, dedicated Search Terms screen, Negative/Budget/Dayparting rule
builders, Keyword Intelligence, Sync Job Monitor UI, Notifications Centre,
User Management UI. Placement Rules, Opportunity Finder and Competitor
Comparison are Phase 3.

Also outstanding but not engineering work: rotate the secrets, set
`ALERT_WEBHOOK_URL`, and deploy to the VPS — all in `docs/DEPLOYMENT.md`.
