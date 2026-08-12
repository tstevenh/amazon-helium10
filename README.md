# PPC OS

An Amazon Advertising management tool. It pulls your campaign, keyword and
search-term data out of Amazon on a schedule, finds where money is being wasted,
and proposes changes — which a person approves before anything is sent back to
Amazon.

**Nothing is applied to your Amazon account automatically.** Every change needs
a human to click Approve and then Apply, and every applied change can be undone
from the Logs screen. The one exception is Dayparting, and it is switched off
until someone deliberately activates a schedule — see Safety below.

## Using Claude to learn this app

This repository includes a `CLAUDE.md` written for AI assistants. Open this
folder in [Claude Code](https://claude.com/claude-code) and ask questions in
plain English, grounded in the actual code:

- "Why is the Keywords page only showing 2,000 rows?"
- "What does the Zero-order spend rule actually do?"
- "Has anything ever been written to my Amazon account?"
- "Why did last night's sync fail?"
- "Which placement is wasting money?"

You do not need to be an engineer to ask. Be careful about acting on answers
that involve changing settings — see Safety.

## Running it

You need [Docker](https://www.docker.com/products/docker-desktop/) and a `.env`
file (ask whoever set this up — it is deliberately not in the repository,
because it contains your Amazon credentials).

```bash
cp .env.example .env    # then fill in the real values
docker compose up -d
```

Open **http://localhost:3000**. Default login is `admin@example.com` /
`ChangeMe123!` — change this before deploying anywhere shared.

To stop: `docker compose down`. Your data survives between runs.

**If port 3000 seems to show the wrong app**, something else is bound to it.
`lsof -nP -iTCP:3000 -sTCP:LISTEN` will show you what.

## The screens

### Daily work

**Dashboard** — starts with whether your data is current, then a "Needs a look"
panel of campaigns that changed sharply in the last few days versus the two
weeks before. Not threshold breaches — *changes*. Then your money, then what is
waiting for you.

**Campaign Manager** — every campaign with spend, sales, ACOS and ROAS, sorted
by spend.

**Ad Groups / Keywords** — the same metrics one and two levels down. The
Keywords screen shows the top 2,000 by spend out of ~220,000; the rest spent
nothing in the period, so they are not hidden from you so much as empty.

**Search Terms** — what shoppers actually typed to reach your ads. Where wasted
spend shows up first, and the data the suggestion engine reads.

**Placements** — the same spend split by *where* the ad appeared: top of search,
product pages, or the rest of search. Amazon lets you bid a percentage more for
a placement, so this is how you find out whether you are paying top-of-search
prices for product-page results.

**Suggestions** — the inbox. Each row proposes one change and says why, in
numbers. Approve the ones you agree with, then Apply.

**Logs** — every change that actually reached Amazon, with an Undo button that
restores the previous value.

### Configuration

**Rules** — the thresholds that generate suggestions. Five kinds: negative
keywords, keyword harvesting, bid changes, budget changes, and placement
adjustments. "Start from template" gives you four vetted starting points if you
do not know what a sensible threshold looks like. Rules **only create
suggestions** — they never touch Amazon.

**Dayparting** — pause and re-enable campaigns by hour and weekday, on a grid
you paint. You choose the hours; the app does not recommend them (Amazon does
not expose hourly performance data). Schedules are created stopped.

**Keyword Intelligence** — your own keyword history, built from Helium 10
Cerebro exports you upload. Four tabs: Trends over time, Opportunities (five
patterns, including keywords you are not bidding on), Compare Competitor
(keyword gaps against a rival ASIN), and the import itself. Nothing is fetched
automatically — you upload on whatever cadence suits you.

### Settings

**Accounts** — your marketplaces and a manual sync trigger.

**Notifications** — every alert the app produced, whether or not it could be
delivered. Includes a daily digest you can preview or send on demand.

**Sync Monitor** — every sync, whether it worked, and plain-English reasons when
it did not.

**Users** — add teammates, set passwords, change roles, disable access. Admin
only.

Note the **Marketplace** selector in the header. US, CA and MX hold entirely
separate data. If a screen looks empty, check you are not looking at a
marketplace with no campaigns.

## How syncing works

A background job pulls fresh data from Amazon every 6 hours, rules are evaluated
daily, and a digest goes out once a day. You can also sync manually from
Accounts.

Syncs are slow — Amazon takes 20–40 minutes to generate each report, and a full
90-day pull is nine of them. That is Amazon's pace, not the app's.

Data accumulates. Amazon only serves a rolling window; the app keeps everything
it has ever pulled, so your history lengthens the longer you run it.

## Safety

Writing to Amazon is controlled by one switch, `AMAZON_WRITE_ENABLED`, which is
**off by default**. With it off you can use the whole app — sync, browse,
generate and approve suggestions — and nothing can reach your ads account.
Applying a suggestion fails with a clear message instead.

The app can do exactly six things to Amazon, and no more:

1. Change a keyword bid
2. Change a product-target bid
3. Add a negative keyword
4. Change a campaign's daily budget
5. Pause or re-enable a campaign (dayparting only)
6. Change a campaign's placement bid adjustments

It cannot create campaigns, ad groups or ads, and it cannot delete or archive
anything. Those limits are in the code, not in configuration. `ARCHIVED` is
refused outright because Amazon cannot undo it.

Every attempt is recorded *before* it is made, and only confirmed changes get a
Logs entry — so a failure can never look like a success.

**Dayparting is the one exception to per-change approval.** You approve a
schedule once, and it then pauses and re-enables those campaigns hourly without
asking again. That is deliberate — re-approving every hour is not workable — but
it means a schedule should not be activated without whoever owns the ad spend
agreeing to it.

## Documentation

| File | What it covers |
|---|---|
| `CLAUDE.md` | Architecture and gotchas, written for AI assistants |
| `docs/HANDOVER.md` | Every bug found and fixed, with evidence |
| `docs/DEPLOYMENT.md` | Deploying to a server, rotating secrets, backups |
| `docs/superpowers/plans/` | Implementation plans, including safety rationale |

## Stack

FastAPI + SQLAlchemy + Postgres, Celery + Redis for background jobs, Next.js +
TypeScript + Tailwind for the frontend, all in Docker Compose.

```bash
docker compose exec api python -m pytest tests/ -q       # 290 tests
docker compose exec frontend npx tsc --noEmit            # typecheck
docker compose exec api alembic current                  # schema version
```
