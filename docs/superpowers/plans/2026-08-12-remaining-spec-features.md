# Plan — build every remaining feature in the specs

**Decided 2026-08-12.** The user's instruction: build everything the two spec
documents require *before* deploying to a VPS. Sequencing is theirs; the
deployment concerns (syncs failing while the laptop sleeps, secrets unrotated)
are recorded in `HANDOVER.md` and unchanged by this plan.

Source of truth is `PPC_OS_Merged.docx` and `Helium10_Merged.docx`, not this
file. Where the spec and reality disagree, that is called out below.

---

## Already built (for reference)

MVP in full — auth, accounts, sync, Campaign Manager, bid rules, suggestion
inbox, execution to Amazon (proven against the live account 2026-08-12),
logs, bulk actions. Plus Phase 2's Search Terms, Negative Targeting, Keyword
Harvesting, Dashboard, User Management and Sync Monitor.

---

## Blocked by reality, not by effort

### Amazon has no hourly performance data for Sponsored Products

Probed directly against the live account on 2026-08-12:

| Attempt | Result |
|---|---|
| `timeUnit: HOURLY` + `spCampaigns` | `400 — configuration timeUnit is not supported for this report type` |
| `startDateTime` column | `400 — columns includes invalid values: (startDateTime)` |
| hour column, no `timeUnit` | `400 — Required fields are invalid or missing: configuration timeUnit` |

The spec itself half-acknowledges this in §7.2: performance reports are
*"not available faster than daily aggregation."* But §Dayparting Action
requires *"hourly aggregation of campaign performance over last 14 days by
hour-of-day × day-of-week"* and a heuristic on it. Those two statements
cannot both be satisfied from Amazon's API.

**Consequence:** dayparting splits in two. The schedule and its hourly
executor are buildable now. The automatic recommendation of *which* hours to
pause is not — it needs hourly history that must be self-collected by
sampling cumulative daily totals each hour and differencing them, which only
accumulates going forward. Task D3 builds the collector; the recommendation
engine cannot produce anything useful until ~14 days after it starts running.

### Keyword Tracker data is formally cancelled

`Helium10_Merged` names organic/sponsored rank as H10's real moat, and
`PPC_OS_Merged` cancels it outright: *"NEVER — REMOVED — Decision 2. Not
deferred, formally cancelled."* So two spec'd features — the rank-enriched
Search Terms tab, and Keyword Tracker rules — are **unbuildable by decision,
not by oversight**. They are not in this plan. The spec's own product-owner
note is the reason to keep the H10 subscription: *"Don't cancel Helium10 yet
— keep it until Keyword Intelligence has 3-6 months of accumulated
snapshots."*

---

## Order of work

Smallest and safest first; anything that writes to Amazon comes after the
things that cannot. Dayparting is deliberately last so its sign-off can be
obtained in parallel.

### T1 — Rule Templates  ·  no Amazon writes

Spec: `/rule-templates (GET/POST)`. §4.3 notes cloning a rule is "simpler and
more immediately useful" — already built, so templates add the *starting
points* a new user has no way to invent.

- `rule_templates` table: name, description, rule_type, configuration_json,
  is_builtin, created_by
- Seed the built-ins from the rules already proven on this account
- "New from template" on the Rules screen

### T2 — Notifications  ·  no Amazon writes

Spec §8.9: `notification_rules` (event_type, channel[slack|email],
threshold_config, is_active), `notification_log` (payload, delivery_status),
and a `settings` table to replace env-var defaults.

§4.3 flags the highest-value slice explicitly: *"lightweight daily digest —
scheduled Slack message summarizing pending/approved/executed counts. Cheap,
high value, independent of full Notifications subsystem."* Build that first.

- Reuse the existing `send_alert` webhook plumbing
- In-app Notifications Centre reading `notification_log`
- Email channel is spec'd but there is no mail transport in this app; ship
  Slack/webhook and record email as unimplemented rather than pretending

### T3 — Budget Rules  ·  **new Amazon write endpoint**

Spec: reuses the `/rules` framework with `rule_type='budget'`, reads
`campaign_performance_daily`, campaign-scoped, same condition/action model as
bid rules.

- **GUARD (spec, verified from Adtomic): skip campaigns under 3 days old** —
  72-hour processing window for new campaigns
- Partial unique `(rule_id, campaign_id) WHERE status='pending'`
- Fourth write operation: campaign budget via `PUT /sp/campaigns`. Same
  contract as the existing three — `assert_write_enabled()` first, 200/207
  with per-item errors parsed properly, attempt recorded before the call
- Note: the spec rejects *Amazon's* native Budget Rules API as "redundant
  with our own Rule Engine; would create competing automation sources"

### T4 — Keyword Intelligence v1  ·  independent track, no Amazon API at all

Spec Part 17. Explicitly shares "ZERO tables, ZERO API surface, ZERO UI
components" with core PPC, so it cannot destabilise anything already working.

**Import is manual by design** — §17.1 is emphatic that no scheduled job ever
auto-fetches from Helium10, because that would reintroduce the scraping risk
Decision 2 rules out. A human uploads a file on whatever cadence they choose.

- Tables: `ki_snapshots`, `ki_snapshot_asins`, `ki_keywords`,
  `ki_keyword_metrics`, `ki_column_mappings`, `product_listings`
- Cerebro CSV parser only. §17.6: *"resist building other parsers
  speculatively"* — `ki_column_mappings` gives a no-code path for other
  sources via Custom CSV
- `file_hash` duplicate detection, warn but allow re-import
- `raw_row` JSONB keeps every original column so unmodelled fields are never
  lost
- Screens: Import Snapshot, Snapshot History, Keyword Trends (multi-line
  chart of search_volume / organic_rank / sponsored_rank / competitor_count
  across snapshots)

### T5 — Dayparting  ·  **new Amazon write endpoint + acts unattended**

**Requires explicit stakeholder sign-off before it ships.** Spec: *"a
deliberate, narrow exception requiring explicit stakeholder sign-off before
Sprint 7."* This is the only feature in the app that changes the account
without a human approving each occurrence.

The exception is well-reasoned and worth restating: a dayparting *suggestion*
goes through normal approval; once approved and activated, its hourly
executions fire on their time trigger, because *"re-approving every single
hour in real time is not operationally possible."*

- D1: tables `dayparting_schedules`, `dayparting_schedule_scope`,
  `dayparting_entries` (day_of_week, hour_start, hour_end,
  action_type[pause|enable|bid_adjust], bid_multiplier)
- D2: schedule builder UI — Mon–Sun × hour-block grid
- D3: hourly sampling collector, the only path to hour-of-day history given
  the API limitation above. Useless for ~14 days after it starts
- D4: hourly executor with **per-marketplace time zones** — US, CA and MX do
  not share a clock, and "6am" is three different moments
- D5: fifth write operation, campaign state via `PUT /sp/campaigns`. This is
  the most dangerous write in the app: a bad bid costs cents, ads left off
  all day costs a day of sales
- D6: recommendation heuristic — flag hour blocks with ACoS > 1.5× the daily
  average as pause candidates; above-average CVR with below-average ACoS as
  increase candidates. Gated on having ≥14 days of sampled data

### T6 — Phase 3

- Placement Rules (spec sequences these after dayparting)
- Anomaly Detection + the Dashboard anomaly panel
- Keyword Intelligence v2 — Opportunity Finder (5 patterns) and Competitor
  Comparison. §17.6: *"don't build Opportunity Finder until there are ≥3 real
  snapshots per ASIN"*, so this is genuinely gated on data, not effort

---

## Constraints that hold throughout

- `AMAZON_WRITE_ENABLED` stays the master switch. Every new write operation
  calls `assert_write_enabled()` before touching the network
- No direct write endpoints on campaigns or targets. Spec §21: *"even a
  manual change goes through POST /suggestions → approve → execute"* — no
  `PATCH /targets/{id}` shortcut, ever
- Every mutation records its attempt before the API call and writes
  `change_log` only on confirmation, so rollback can never undo a
  no-op
- New status/enum values must match their database CHECK constraints. Unit
  tests here do not touch Postgres, so a value the DB rejects passes green —
  this has already cost a debugging session once
- Verify in a browser, not with `curl`. Several bugs in this project were
  client-side only while every API call returned 200
