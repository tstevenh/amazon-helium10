#!/usr/bin/env bash
#
# Deploy an UPDATE to the comfecto server, including schema migrations.
#
#   cd ~/ppc-os && bash scripts/update-comfecto.sh
#
# Different from deploy-comfecto.sh, which is for a first install: this assumes
# the stack already runs, keeps .env untouched, and never goes near nginx.
#
# Order matters here and is not arbitrary:
#
#   1. Back up the database FIRST. A migration is the one routine operation that
#      can lose data, and 025 was written after 023's own first attempt aborted
#      halfway.
#   2. Refuse to run while a sync is in progress. A 90-day pull is hours of work
#      and rebuilding the worker throws it away.
#   3. Stop worker and beat BEFORE migrating. Otherwise a scheduled job can run
#      new code against the old schema, or old code against the new one, for the
#      seconds the migration takes.
#   4. Migrate with only the API up.
#   5. Bring everything back and verify.
set -uo pipefail

COMPOSE="sudo docker compose -f docker-compose.yml -f docker-compose.behind-nginx.yml"
DOMAIN="ads.comfecto.com"

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m !  %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m !! %s\033[0m\n' "$*" >&2; exit 1; }

[[ -f docker-compose.yml ]] || die "Run this from inside the ppc-os directory."

# ── 1. Refuse to clobber a running sync ────────────────────────────────────
say "Checking nothing important is running"
ACTIVE="$($COMPOSE exec -T postgres psql -U ppc_os -d ppc_os -tAc \
  "SELECT count(*) FROM sync_jobs WHERE status IN ('queued','running');" 2>/dev/null | tr -d '[:space:]')"
if [[ "${ACTIVE:-0}" != "0" ]]; then
    $COMPOSE exec -T postgres psql -U ppc_os -d ppc_os -c \
      "SELECT id, status, started_at FROM sync_jobs WHERE status IN ('queued','running');" || true
    warn "A sync is queued or running. Rebuilding the worker will abandon it."
    warn "Either wait for it to finish, or re-run with FORCE=1 to proceed anyway."
    [[ "${FORCE:-0}" == "1" ]] || die "Stopped. Nothing was changed."
fi
echo "  no active sync"

# ── 2. Back up before touching the schema ──────────────────────────────────
say "Backing up the database"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$HOME/ppc-os-backup-${STAMP}.sql.gz"
$COMPOSE exec -T postgres pg_dump -U ppc_os ppc_os | gzip > "$BACKUP" \
    || die "Backup failed. Refusing to migrate without one."
SIZE="$(du -h "$BACKUP" | cut -f1)"
# A pg_dump that "succeeds" and writes 20 bytes is a failure with a zero exit.
[[ "$(stat -c%s "$BACKUP" 2>/dev/null || stat -f%z "$BACKUP")" -gt 10000 ]] \
    || die "Backup is suspiciously small ($SIZE). Investigate before migrating."
echo "  $BACKUP ($SIZE)"

# ── 3. New code ────────────────────────────────────────────────────────────
say "Fetching the new code"
BEFORE="$(git rev-parse --short HEAD)"
git pull --ff-only || die "git pull failed. Resolve it and re-run."
AFTER="$(git rev-parse --short HEAD)"
if [[ "$BEFORE" == "$AFTER" ]]; then
    warn "Already at $AFTER — nothing new to deploy."
else
    echo "  $BEFORE -> $AFTER"
    git --no-pager log --oneline "${BEFORE}..${AFTER}" | sed 's/^/    /'
fi

say "Building images"
$COMPOSE build || die "Build failed. Nothing was deployed; the old stack is still running."

# ── 4. Migrate with background work stopped ────────────────────────────────
say "Stopping worker and beat for the migration"
$COMPOSE stop worker beat

say "Starting the new API"
$COMPOSE up -d postgres redis api || die "API did not start."
for _ in $(seq 1 30); do
    $COMPOSE exec -T api curl -fsS -o /dev/null http://localhost:8000/health 2>/dev/null && break
    sleep 2
done

say "Current schema version"
$COMPOSE exec -T api alembic current 2>&1 | tail -2

say "Applying migrations"
if ! $COMPOSE exec -T api alembic upgrade head; then
    warn "MIGRATION FAILED. Alembic uses transactional DDL, so the schema is"
    warn "almost certainly unchanged — but verify before doing anything else:"
    warn "  $COMPOSE exec -T api alembic current"
    warn "Restore from the backup only if the schema is genuinely half-applied:"
    warn "  gunzip -c $BACKUP | $COMPOSE exec -T postgres psql -U ppc_os -d ppc_os"
    die "Stopped with worker and beat still down, on purpose."
fi
$COMPOSE exec -T api alembic current 2>&1 | tail -1

# ── 5. Everything back up ──────────────────────────────────────────────────
say "Starting the rest of the stack"
# `up -d` rather than `start`: it recreates containers, which is the only way a
# changed .env is picked up. `restart` keeps the old environment.
$COMPOSE up -d || die "Stack did not come up. Check: $COMPOSE ps"

say "Waiting for the frontend"
for _ in $(seq 1 45); do
    curl -fsS -o /dev/null http://127.0.0.1:3000 2>/dev/null && { echo "  answering"; break; }
    sleep 2
done

say "Verifying"
$COMPOSE ps --format 'table {{.Service}}\t{{.Status}}'
echo
echo "  schema:  $($COMPOSE exec -T api alembic current 2>/dev/null | tail -1)"
echo "  writes:  AMAZON_WRITE_ENABLED=$($COMPOSE exec -T api printenv AMAZON_WRITE_ENABLED 2>/dev/null)"
echo "  public:  HTTP $(curl -s -o /dev/null -w '%{http_code}' "https://${DOMAIN}/login" || echo 000)"
echo
# The frontend proxy destination is baked in at build time, so a bad build shows
# up as every /backend call returning 500 while the API itself is healthy.
PROXY="$($COMPOSE exec -T frontend grep -o 'http://[a-z0-9.:]*8000' .next/routes-manifest.json 2>/dev/null | head -1)"
echo "  proxy:   ${PROXY:-UNKNOWN}"
[[ "$PROXY" == "http://api:8000" ]] || warn "Proxy target should be http://api:8000 — /backend calls will 500."

cat <<DONE

────────────────────────────────────────────────────────────────────────
 Updated.  https://${DOMAIN}

 Backup:   $BACKUP
 Rollback: git checkout $BEFORE && bash scripts/update-comfecto.sh
           (schema migrations are NOT undone by that — see docs/DEPLOYMENT.md)

 Writes to Amazon are whatever .env says. Changing that is a separate,
 deliberate step: bash scripts/enable-writes.sh
────────────────────────────────────────────────────────────────────────
DONE
