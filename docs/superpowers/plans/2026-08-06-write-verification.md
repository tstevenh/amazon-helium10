# Amazon Write Verification

Live account `85e0e890-6baf-45ef-b8de-026c07f050e0`, US profile
`89389798686160`. Date: 2026-08-06.

## Part 1 — Can the app write to Amazon at all? ✅ YES

This is the question the team's own spec called the scariest unknown in the
whole system:

> *"'Can we actually change a live bid on Amazon and have it stick' is the
> scariest unknown in the whole system; it should be de-risked in Week 2, not
> discovered as a surprise in Week 4 after building an entire approval UI on
> top of an unproven assumption."*

It had never been attempted. It has now been answered for the *create* case.

### What was created

Per the team's constraint — *"never test on existing campaign, create 1 new
campaign for test"* — a purpose-built, inert campaign:

| Object | Amazon ID | Detail |
|---|---|---|
| Campaign | `153113201181536` | `ZZ-API-TEST-DO-NOT-USE`, **PAUSED**, $1.00/day, MANUAL |
| Ad group | `73870484391913` | `ZZ-API-TEST-ADGROUP`, no product ads |
| Keyword | `158984831925681` | `zzapitestdonotuse`, EXACT, bid **$0.75** |

Inert three times over: the campaign is paused, the ad group has no product
ads so it cannot serve even if unpaused, and the keyword text is nonsense so
it could never match a real shopper query.

Created by `scripts/create_test_campaign.py` — a **standalone script, not part
of the application**. The app's write client remains limited to three
endpoints and cannot create campaigns; a test enforces this.

### All three calls succeeded

Each returned `HTTP 207` with `"error": []` and a populated `success` array.
Worth stating explicitly: `207` alone does **not** mean success on these
endpoints — v3 returns `207` for rejections too, with the failure inside a
per-item error array. The success here is the empty `error` list, not the
status code.

### Independently verified

Rather than trusting the write responses, the objects were read back from
Amazon through the normal read client:

```
campaign found  : 1
   id=153113201181536 name=ZZ-API-TEST-DO-NOT-USE status=paused budget=1.0 targeting=manual
keyword found   : 1
   id=158984831925681 text=zzapitestdonotuse match=exact bid=0.75 status=enabled
```

Then synced into Postgres. Counts moved by exactly one at each level:
campaigns 289 → **290**, ad groups 1,422 → **1,423**, targets 231,798 →
**231,799**.

### The kill-switch behaved correctly throughout

A first attempt **failed safely**: `AMAZON_WRITE_ENABLED` was documented in
`.env.example` but absent from the real `.env`, so `sed` had nothing to flip
and the setting fell back to its code default of `False`. The write was
blocked and nothing was created — confirmed by reading Amazon afterwards
(267 campaigns, zero `ZZ-API-TEST`).

That is the design working: **the safe default holds even when configuration
is missing.** The variable was then added to `.env`, and the wrapper script
now asserts the container actually picked up the change before attempting
anything.

Writes were switched off again immediately after creation and confirmed off.

## Part 2 — Can the app CHANGE an existing bid, and undo it? ⏳ NOT YET

Still outstanding, and it is the part that matters for the product:

- [ ] Change keyword `158984831925681` from **$0.75 → $0.85** via
      `ExecutionService`
- [ ] Re-sync and confirm Amazon reports `$0.85`
- [ ] **Roll back** to `$0.75` via `RollbackService`
- [ ] Re-sync and confirm `$0.75` returned

Blocked on Plan 3 Tasks 5 and 6 (execution task, API wiring, rollback), and
gated on team authorisation for the update itself.

**The rollback matters as much as the write.** The spec admits there is no
undo today; proving the write works without proving the undo works would be
the wrong result to celebrate.

## Cleanup

Amazon does not permit hard deletion of campaigns. When testing is finished,
**archive** `ZZ-API-TEST-DO-NOT-USE` in the Amazon Ads console. It will remain
visible in historical reports as an archived campaign with zero spend.
