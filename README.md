# PPC OS

An Amazon Advertising management tool. It pulls your campaign, keyword and
search-term data out of Amazon on a schedule, finds the keywords that are
losing money, and proposes changes — which a person approves before anything
is sent back to Amazon.

**Nothing is ever applied to your Amazon account automatically.** Every change
requires a human to click Approve and then Apply, and every applied change can
be undone from the Logs screen.

## Using Claude to learn this app

This repository includes a `CLAUDE.md` written for AI assistants. If you open
this folder in [Claude Code](https://claude.com/claude-code) you can ask
questions in plain English and get answers grounded in the actual code:

- "Why is the Keywords page only showing 2,000 rows?"
- "What does the Zero-order spend rule actually do?"
- "Has anything ever been written to my Amazon account?"
- "Why did last night's sync fail?"

You do not need to be an engineer to ask. You do need to be careful about
acting on answers that involve changing settings — see Safety below.

## Running it

You need [Docker](https://www.docker.com/products/docker-desktop/) and a
`.env` file (ask whoever set this up — it is not in the repository, on
purpose, because it contains your Amazon credentials).

```bash
cp .env.example .env    # then fill in the real values
docker compose up -d
```

Open **http://localhost:3000**. Default login is `admin@example.com` /
`ChangeMe123!` — change this before deploying anywhere shared.

To stop: `docker compose down`. Your data stays in the database between runs.

## The screens

**Campaign Manager** — every campaign with spend, sales, ACOS and ROAS.
Sorted by spend, highest first.

**Ad Groups / Keywords** — the same metrics one and two levels down. The
Keywords screen shows the top 2,000 by spend out of ~220,000; the rest spent
nothing in the period, so they are not hidden from you so much as empty.

**Search Terms** — what shoppers actually typed to reach your ads. This is
where wasted spend shows up first, and it is the data the suggestion engine
reads.

**Suggestions** — the inbox. Each row proposes one change: add a negative
keyword, harvest a converting search term into its own keyword, or raise or
lower a bid. Each says why, in numbers. Approve the ones you agree with, then
Apply.

**Rules** — the thresholds that generate suggestions. "Zero-order spend"
finds terms that cost money and produced no orders; "Bid down on high ACOS"
finds keywords whose ACOS is above your target. You can edit these, clone
them, or write your own. Rules **only create suggestions** — they never touch
Amazon.

**Logs** — every change that actually reached Amazon, with an Undo button
that restores the previous value.

**Accounts** — your marketplaces and a manual sync trigger.

Note the **Marketplace** selector in the header. US, CA and MX hold entirely
separate data. If a screen looks empty, check you are not looking at a
marketplace with no campaigns.

## How syncing works

A background job pulls fresh data from Amazon every 6 hours, and rules are
evaluated once a day. You can also sync manually from Accounts.

Syncs are slow — Amazon takes 23–40 minutes to generate each report, and a
full 90-day pull is nine of them. This is Amazon's pace, not the app's.

Data accumulates. Amazon only serves a rolling window, but the app keeps
everything it has ever pulled, so your history gets longer the longer you run
it.

## Safety

Writing to Amazon is controlled by a single switch, `AMAZON_WRITE_ENABLED`,
which is **off by default**. With it off you can use the entire app — sync,
browse, generate and approve suggestions — and nothing can reach your ads
account. Applying a suggestion fails with a clear message instead.

The app can only do three things to Amazon: change a keyword bid, change a
product-target bid, and add a negative keyword. It cannot create, pause,
delete or archive campaigns, and it cannot change budgets. That limit is in
the code, not in configuration.

Every attempt is recorded before it is made, and only confirmed changes get a
Logs entry — so a failure can never look like a success.

## Documentation

| File | What it covers |
|---|---|
| `CLAUDE.md` | Architecture and gotchas, written for AI assistants |
| `docs/HANDOVER.md` | Every bug found and fixed, with evidence |
| `docs/DEPLOYMENT.md` | Deploying to a server, rotating secrets, backups |

## Stack

FastAPI + SQLAlchemy + Postgres, Celery + Redis for background jobs, Next.js
+ TypeScript + Tailwind for the frontend, all in Docker Compose.

```bash
docker compose exec api python -m pytest tests/ -q
```
