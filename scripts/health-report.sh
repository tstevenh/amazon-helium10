#!/usr/bin/env bash
#
# Read-only health report for PPC OS. Run it, paste the output.
#
#   cd ~/ppc-os && bash scripts/health-report.sh
#
# Every command here reads. Nothing starts, stops, rebuilds or modifies
# anything, and every docker command is scoped to this compose project — the
# other projects on this host are never named and never touched.
#
# Safe to run at any time, including during a sync.
set -uo pipefail   # deliberately NOT -e: one failing section must not abort
                   # the report, since a section failing IS a finding.

COMPOSE="sudo docker compose -f docker-compose.yml -f docker-compose.behind-nginx.yml"
PSQL="$COMPOSE exec -T postgres psql -U ppc_os -d ppc_os -qAX"

hdr() { printf '\n\033[1;34m── %s %s\033[0m\n' "$*" "$(printf '─%.0s' $(seq 1 $((60 - ${#1}))))"; }

[[ -f docker-compose.yml ]] || { echo "Run this from ~/ppc-os"; exit 1; }

echo "PPC OS health report — $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "host uptime:$(uptime -p 2>/dev/null || uptime)"

hdr "Containers (this project only)"
$COMPOSE ps --format 'table {{.Service}}\t{{.Status}}' 2>&1

hdr "Host resources"
free -h 2>/dev/null | head -2 || echo '(free unavailable)'
df -h / | tail -1
echo "load:$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || echo n/a)"

hdr "Schema version"
$COMPOSE exec -T api alembic current 2>&1 | tail -2

hdr "Amazon connection"
$COMPOSE exec -T api printenv 2>/dev/null \
  | grep -E '^(AMAZON_MOCK_MODE|AMAZON_WRITE_ENABLED|ENV)=' | sort
# Presence, never the value — this output gets pasted into a chat.
for v in AMAZON_CLIENT_ID AMAZON_CLIENT_SECRET FERNET_KEY JWT_SECRET_KEY ALERT_WEBHOOK_URL; do
    if $COMPOSE exec -T api printenv "$v" 2>/dev/null | grep -q '[^[:space:]]'; then
        echo "$v=<set>"
    else
        echo "$v=<EMPTY>"
    fi
done

hdr "Data in the database"
# Only campaigns and search_terms carry profile_id. ad_groups hang off
# campaigns, and targets off ad_groups, so both need the join.
$PSQL -c "
SELECT p.country_code, p.marketplace_code,
       (SELECT count(*) FROM campaigns c
         WHERE c.profile_id = p.id AND c.deleted_at IS NULL) AS campaigns,
       (SELECT count(*) FROM ad_groups g JOIN campaigns c ON c.id = g.campaign_id
         WHERE c.profile_id = p.id AND g.deleted_at IS NULL) AS ad_groups,
       (SELECT count(*) FROM targets t
           JOIN ad_groups g ON g.id = t.ad_group_id
           JOIN campaigns c ON c.id = g.campaign_id
         WHERE c.profile_id = p.id AND t.deleted_at IS NULL) AS targets,
       (SELECT count(*) FROM search_terms s WHERE s.profile_id = p.id) AS search_terms
FROM ads_profiles p ORDER BY p.country_code;" 2>&1

hdr "Performance data coverage"
# The number that matters most. Structural data can be complete while every
# performance report silently returned nothing — the sync still looks healthy,
# but the rules engine has nothing to judge and every screen reads zero.
$PSQL -c "
SELECT 'campaign_performance_daily' AS table, min(date) AS earliest, max(date) AS latest,
       count(*) AS rows FROM campaign_performance_daily
UNION ALL
SELECT 'search_terms', min(date), max(date), count(*) FROM search_terms;" 2>&1

hdr "Last 10 sync jobs"
$PSQL -c "
SELECT status,
       to_char(created_at, 'MM-DD HH24:MI') AS created,
       CASE WHEN finished_at IS NULL THEN 'running/orphan'
            ELSE to_char(finished_at - started_at, 'HH24:MI:SS') END AS duration,
       records_synced AS records,
       left(coalesce(error_message, ''), 70) AS error
FROM sync_jobs ORDER BY created_at DESC LIMIT 10;" 2>&1

hdr "Jobs currently blocking a new sync"
# queued|running is what has_active() checks. Anything here older than ~7h is
# an orphan and is blocking every future sync for that account.
$PSQL -c "
SELECT id, status, round(extract(epoch from (now() - coalesce(started_at, created_at)))/3600, 1) AS age_hours
FROM sync_jobs WHERE status IN ('queued','running');" 2>&1

hdr "Suggestions and rules"
$PSQL -c "SELECT status, count(*) FROM suggestions GROUP BY status ORDER BY 2 DESC;" 2>&1
$PSQL -c "
SELECT rule_type, status, count(*) FROM rules
WHERE deleted_at IS NULL GROUP BY 1,2 ORDER BY 1;" 2>&1

hdr "Changes written to Amazon"
# Expected to be empty while AMAZON_WRITE_ENABLED=false. A row here when
# writes are supposedly off would be the single most serious finding possible.
$PSQL -c "SELECT count(*) AS change_log_rows FROM change_log;" 2>&1

hdr "Unread notifications"
$PSQL -c "
SELECT event_type, delivery_status, count(*), max(sent_at) AS latest
FROM notification_log GROUP BY 1,2 ORDER BY 4 DESC NULLS LAST LIMIT 10;" 2>&1

hdr "Errors in the worker (last 2h)"
$COMPOSE logs worker --since 2h 2>&1 \
  | grep -iE 'error|traceback|exception|failed|critical' \
  | grep -viE 'error_message|0 errors' | tail -25
echo "(empty above = no errors)"

hdr "Errors in the API (last 2h)"
$COMPOSE logs api --since 2h 2>&1 \
  | grep -iE 'error|traceback|exception|critical' \
  | grep -v '"GET /health' | tail -25
echo "(empty above = no errors)"

hdr "Worker activity right now (last 15 lines)"
$COMPOSE logs worker --tail 15 2>&1

echo
echo "── end of report ──"
