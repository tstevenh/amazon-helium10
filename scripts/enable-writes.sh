#!/usr/bin/env bash
#
# Turn Amazon writes ON (or OFF) on the comfecto server, with a pre-flight.
#
#   bash scripts/enable-writes.sh on
#   bash scripts/enable-writes.sh off
#
# Why this is its own script and not a flag on the deploy:
#
# Almost everything in this app needs a human to approve each change — a rule
# produces a SUGGESTION, and somebody clicks Execute. Turning writes on does not
# change that. There is exactly one exception, and it is the reason for the
# checks below: an ACTIVE DAYPARTING SCHEDULE acts on its own, every hour, with
# nobody watching. Flipping this switch while a schedule is active means the next
# reconcile pauses campaigns and moves bids within the hour.
#
# So this reports what would happen before it happens, and makes you type the
# word.
set -uo pipefail

COMPOSE="sudo docker compose -f docker-compose.yml -f docker-compose.behind-nginx.yml"
PSQL="$COMPOSE exec -T postgres psql -U ppc_os -d ppc_os"

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m !  %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m !! %s\033[0m\n' "$*" >&2; exit 1; }

MODE="${1:-}"
[[ "$MODE" == "on" || "$MODE" == "off" ]] || die "Usage: bash scripts/enable-writes.sh on|off"
[[ -f .env ]] || die "No .env here. Run this from inside the ppc-os directory."

CURRENT="$(grep -E '^AMAZON_WRITE_ENABLED=' .env | cut -d= -f2- | tr -d '[:space:]')"
echo "AMAZON_WRITE_ENABLED is currently: ${CURRENT:-unset}"

# ── OFF is never risky; do it immediately ──────────────────────────────────
if [[ "$MODE" == "off" ]]; then
    say "Turning writes OFF"
    sed -i 's/^AMAZON_WRITE_ENABLED=.*/AMAZON_WRITE_ENABLED=false/' .env
    # `up -d` recreates the containers. `restart` reuses the old environment and
    # would leave the running processes still able to write.
    $COMPOSE up -d api worker beat
    sleep 6
    echo
    echo "  in the running process: AMAZON_WRITE_ENABLED=$($COMPOSE exec -T api printenv AMAZON_WRITE_ENABLED)"
    echo "  worker:                 AMAZON_WRITE_ENABLED=$($COMPOSE exec -T worker printenv AMAZON_WRITE_ENABLED)"
    exit 0
fi

# ── Pre-flight for ON ──────────────────────────────────────────────────────
say "PRE-FLIGHT — what will be able to change your account"

echo
echo "1. Dayparting schedules that run WITHOUT asking anyone:"
$PSQL -c "
SELECT s.name,
       s.is_active,
       (SELECT count(*) FROM dayparting_schedule_scope x WHERE x.schedule_id = s.id) AS campaigns,
       (SELECT count(*) FROM dayparting_entries e WHERE e.schedule_id = s.id)        AS windows
FROM dayparting_schedules s
WHERE s.deleted_at IS NULL AND s.is_active
ORDER BY s.name;" 2>&1

ACTIVE_DP="$($PSQL -tAc "SELECT count(*) FROM dayparting_schedules WHERE deleted_at IS NULL AND is_active;" 2>/dev/null | tr -d '[:space:]')"
if [[ "${ACTIVE_DP:-0}" != "0" ]]; then
    warn "$ACTIVE_DP active dayparting schedule(s). These will act within the hour,"
    warn "unattended. Deactivate any you are not ready for BEFORE continuing:"
    warn "  Dayparting screen -> the schedule -> Deactivate"
else
    echo "   none — nothing will act unattended."
fi

echo
echo "2. Rules. These only create SUGGESTIONS; a human still clicks Execute."
$PSQL -c "
SELECT r.rule_type, r.status, count(*) AS rules,
       sum(CASE WHEN (SELECT count(*) FROM rule_campaign_scope s WHERE s.rule_id = r.id) = 0
                 AND (SELECT count(*) FROM rule_ad_group_scope g WHERE g.rule_id = r.id) = 0
                THEN 1 ELSE 0 END) AS unscoped
FROM rules r WHERE r.deleted_at IS NULL
GROUP BY r.rule_type, r.status ORDER BY r.rule_type;" 2>&1
echo "   'unscoped' means the rule considers every campaign in the marketplace."

echo
echo "3. How fresh the data is. Stale numbers produce confident, wrong decisions."
$PSQL -c "
SELECT status, to_char(created_at,'MM-DD HH24:MI') AS created,
       to_char(finished_at,'MM-DD HH24:MI') AS finished
FROM sync_jobs ORDER BY created_at DESC LIMIT 3;" 2>&1

echo
echo "4. Where failures will be reported:"
if $COMPOSE exec -T api printenv ALERT_WEBHOOK_URL 2>/dev/null | grep -q '[^[:space:]]'; then
    echo "   ALERT_WEBHOOK_URL is set."
else
    warn "ALERT_WEBHOOK_URL is EMPTY. Failed writes will be recorded in the app"
    warn "and nobody will be told. Strongly consider setting it first."
fi

echo
echo "5. Changes already written to Amazon by this app so far:"
$PSQL -c "SELECT count(*) AS change_log_rows, max(changed_at) AS most_recent FROM change_log;" 2>&1

cat <<'NOTE'

────────────────────────────────────────────────────────────────────────
 What turning this ON does and does not do

   DOES     let an approved suggestion actually reach Amazon when someone
            clicks Execute
   DOES     let ACTIVE dayparting schedules pause campaigns and change bids
            on their own, hourly
   DOES NOT auto-apply any suggestion — every one still needs a human
   DOES NOT create or delete anything: there is no create and no delete
            anywhere in this app, and archived campaigns are refused

 Proven live against Amazon: keyword bids, campaign pause/enable, dayparting
 bid windows. NOT proven live: budget changes and placement adjustments — if a
 budget rule is executed, that path runs for the first time on your account.
────────────────────────────────────────────────────────────────────────
NOTE

echo
read -r -p "Type ENABLE WRITES to continue, anything else to abort: " CONFIRM
[[ "$CONFIRM" == "ENABLE WRITES" ]] || die "Aborted. Nothing changed."

say "Turning writes ON"
if grep -qE '^AMAZON_WRITE_ENABLED=' .env; then
    sed -i 's/^AMAZON_WRITE_ENABLED=.*/AMAZON_WRITE_ENABLED=true/' .env
else
    echo 'AMAZON_WRITE_ENABLED=true' >> .env
fi

$COMPOSE up -d api worker beat
sleep 8

say "Confirming the RUNNING processes, not just the file"
echo "  api    : AMAZON_WRITE_ENABLED=$($COMPOSE exec -T api printenv AMAZON_WRITE_ENABLED)"
echo "  worker : AMAZON_WRITE_ENABLED=$($COMPOSE exec -T worker printenv AMAZON_WRITE_ENABLED)"
echo "  beat   : AMAZON_WRITE_ENABLED=$($COMPOSE exec -T beat printenv AMAZON_WRITE_ENABLED)"

cat <<'DONE'

 Writes are ON.

 Watch it: the Logs screen shows every confirmed change, newest first, with an
 Undo on each one. From the shell:
   sudo docker compose -f docker-compose.yml -f docker-compose.behind-nginx.yml \
     logs -f worker | grep amazon_write

 Turn it off at any time:
   bash scripts/enable-writes.sh off
DONE
