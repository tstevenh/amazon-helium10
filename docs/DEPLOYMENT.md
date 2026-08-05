# PPC OS — Deployment

Target: a single VPS running Docker Compose behind a reverse proxy, used
internally by the team. Not a multi-tenant public product.

## Before you start

Everything below assumes the `sync-honesty` and `background-worker` work is
merged. Check:

```bash
docker compose exec api python -m pytest tests -q   # expect all passing
docker compose exec api alembic current             # expect 013
```

## Services

| Service | Purpose | Host port |
|---|---|---|
| `postgres` | database | none (compose network only) |
| `redis` | Celery broker | none |
| `api` | FastAPI | `127.0.0.1:8000` |
| `frontend` | Next.js | `127.0.0.1:3000` |
| `worker` | Celery worker — runs syncs | none |
| `beat` | Celery Beat — schedules syncs and health checks | none |

**Both host ports bind to loopback only.** A reverse proxy terminates TLS in
front of them. Nothing in this stack listens on a public interface.

Run with the base file only on a server — the override file is for local
development and would start the frontend dev server:

```bash
docker compose -f docker-compose.yml up -d --build
```

## Reverse proxy and TLS

Terminate TLS at Caddy or nginx and proxy to `127.0.0.1:3000`. The frontend
proxies `/backend/*` to the API itself, so the API does not need to be
exposed separately.

A minimal Caddyfile:

```
ppc.example.com {
    reverse_proxy 127.0.0.1:3000
}
```

## Amazon OAuth — must be updated for the new domain

Two changes, and **both** are required or the connection breaks:

1. Set in `.env`:
   `AMAZON_REDIRECT_URI=https://ppc.example.com/accounts/oauth/callback`
   and `FRONTEND_URL=https://ppc.example.com`
2. Register that exact redirect URI in the Amazon LWA app (Amazon Developer
   Console). Amazon requires HTTPS for any non-localhost redirect URI, and the
   value must match character-for-character.

Then re-run the OAuth flow for each account from the Accounts page.

**Upside of moving off localhost:** the redirect URI stops being
machine-specific. Whoever holds the Amazon login grants consent once, from
anywhere, and the whole team shares that connection.

## Secret rotation — required, and order matters

The current `.env` values were present in plaintext in a `Downloads` folder
and must be treated as compromised. Generate replacements:

```bash
python3 -c 'import secrets; print("JWT_SECRET_KEY=" + secrets.token_urlsafe(48))'
python3 -c 'import secrets; print("POSTGRES_PASSWORD=" + secrets.token_urlsafe(24))'
docker compose exec -T api python -c "from cryptography.fernet import Fernet; print('FERNET_KEY=' + Fernet.generate_key().decode())"
```

Apply in this order:

1. **`JWT_SECRET_KEY`** — invalidates existing logins only. Harmless.
2. **`POSTGRES_PASSWORD`** — must be changed in `.env` **and** on the database
   role, or the app cannot connect:
   ```bash
   docker compose exec postgres psql -U ppc_os -d postgres -c "ALTER USER ppc_os WITH PASSWORD '<new>';"
   ```
3. **`AMAZON_CLIENT_SECRET`** — rotate in the Amazon Developer Console, then
   update `.env` to match.
4. **`FERNET_KEY` — LAST, and it is destructive.** It encrypts the stored
   Amazon refresh tokens at rest. Rotating it makes every existing token
   undecryptable, so **OAuth must be re-run for every account immediately
   afterwards**. Do this when someone with the Amazon login is available.
5. **`SEED_ADMIN_PASSWORD` / `SEED_USER_PASSWORD`** — change from
   `ChangeMe123!`. Note the seed script is idempotent and will not overwrite
   existing users, so change these through the app or a one-off script; editing
   `.env` alone does nothing to accounts that already exist.

## Background sync configuration

| Variable | Default | Notes |
|---|---|---|
| `SYNC_SCHEDULE_HOURS` | `6` | `0` disables periodic sync. Health checks still run. |
| `AMAZON_REPORT_POLL_MAX_ATTEMPTS` | `1440` | ×10s = 4 hours. Amazon's report queue was measured at 23–40 min per report and is highly variable; the old 180-attempt (~40 min) ceiling abandoned ad-group and keyword reports every time. |
| `AMAZON_FETCH_MAX_RETRIES` | `4` | Retries transport errors and HTTP 429/5xx. |
| `ALERT_WEBHOOK_URL` | *(empty)* | Slack/Discord/n8n webhook. Empty means alerts are logged at `ERROR` only. **Set this in production.** |
| `SYNC_STALE_AFTER_HOURS` | `24` | An account with no successful sync inside this window is reported stale. |

Expect a 30-day sync to take **around an hour** — most of it waiting on
Amazon's report queue, not on this app.

## Monitoring

`GET /health` — liveness and Amazon config completeness.
`GET /health/sync` — sync freshness. Unauthenticated, exposes no ad data,
always returns 200. Read the `healthy` field:

```json
{"failed_recent": [], "stale_accounts": [], "healthy": true}
```

Point an uptime monitor at `/health/sync` and alert when `healthy` is false.
Beat also runs `check_sync_health` every 30 minutes and posts to
`ALERT_WEBHOOK_URL` when a job ends `failed` or `partial`, or an account goes
stale. Alerts fire only on real problems — a channel that fires when
everything is fine gets muted, and then failures are invisible again.

## Backups

`scripts/backup-db.sh` dumps Postgres, refuses to keep a suspiciously small
dump, and rotates after 14 days.

```
0 3 * * * cd /opt/ppc-os && ./scripts/backup-db.sh >> /var/log/ppc-os-backup.log 2>&1
```

**Test the restore.** An untested backup is not a backup:

```bash
docker compose exec -T postgres psql -U ppc_os -d postgres -c "CREATE DATABASE restore_test;"
docker compose exec -T postgres pg_restore -U ppc_os -d restore_test --no-owner < /var/backups/ppc-os/<file>.dump
docker compose exec -T postgres psql -U ppc_os -d restore_test -c "SELECT count(*) FROM targets;"
docker compose exec -T postgres psql -U ppc_os -d postgres -c "DROP DATABASE restore_test;"
```

The count should match production. Verified 2026-08-05: a restore returned
231,798 targets, matching exactly.

Copy dumps off the server. One VPS with local-only backups is one disk failure
from total loss.

## ⚠️ `docker compose down -v` destroys the database

The `-v` flag deletes the `postgres_data` volume. There is no undo. Use
`docker compose down` without `-v` to stop the stack.

Consolidating onto one server also removes the accidental redundancy the team
had while everyone ran their own copy — the backup cron is what replaces it.

## Upgrading

```bash
cd /opt/ppc-os
git pull
docker compose -f docker-compose.yml up -d --build
docker compose exec api alembic upgrade head
docker compose exec api python -m pytest tests -q
```

The `api` entrypoint runs migrations on start, so the explicit `alembic
upgrade head` is belt-and-braces. The `worker` and `beat` containers clear the
image entrypoint deliberately and do **not** run migrations.

### ⚠️ Restart the worker whenever tasks change

Celery registers tasks at worker startup from the `include` list in
`app/worker/celery_app.py`. Adding a task, or changing a task's signature,
requires **recreating the worker** — a running one will reject the unknown
task with `KeyError: '<task_name>'` and, because Beat keeps firing on
schedule, do so silently and repeatedly.

This bit during development: Beat fired `check_sync_health` every 30 minutes
for an hour while the worker rejected every one, because the worker predated
the task being added.

```bash
docker compose up -d --force-recreate worker beat
```

Then confirm from the worker's own startup banner, rather than assuming:

```bash
docker compose logs worker --since 1m | sed -n '/\[tasks\]/,/celery@/p'
```

Expect `check_sync_health`, `enqueue_scheduled_syncs`, `ping`, `sync_account`.

Note the app volume-mounts `app/`, so ordinary code edits take effect on
restart — but the task *registry* is only read at startup.

### Sync windows

| Trigger | Window | Duration |
|---|---|---|
| Beat, every 6 h | 3-day rolling | ~30 min |
| Sync All button | 3-day rolling | ~30 min |
| A profile's first ever sync | 90 days (automatic) | 6–12 h |
| `POST /sync-all?perf_days=90` | 90 days (deliberate backfill) | 6–12 h |

The 3-day rolling window is not a shortcut: Amazon attributes conversions over
7 days, so recent days genuinely need re-fetching while older days are final.
History accumulates because performance rows are upserted per
`(entity, date)` — **nothing ever deletes historical rows.**

**Amazon only retains ~90–95 days of report data.** Anything older that you
have not already captured is unrecoverable. Once past that window your
Postgres is the *only* place the history exists, which is what makes the
backup cron an asset rather than hygiene.

## Known limitations

- **No writes to Amazon.** By deliberate team constraint, the app reads and
  recommends; a human applies changes in Amazon's console. This is the main
  functional gap versus Helium 10's Adtomic.
- **No staging environment.** Changes go straight to production.
- **No redundancy.** One VPS, one database, no failover.
- **Test coverage is the sync layer plus pinned contracts.** Auth and the API
  endpoints have none.
- **The Dashboard module is unbuilt** — still a "Soon" label.
