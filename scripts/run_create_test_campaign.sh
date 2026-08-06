#!/bin/sh
# Create the paused API test campaign, with the write kill-switch on for
# exactly as long as it takes and off again afterwards.
#
#   ./scripts/run_create_test_campaign.sh            # dry run, sends nothing
#   ./scripts/run_create_test_campaign.sh --confirm  # actually create it
#
# The switch is turned back off even if creation fails.
set -u

cd "$(dirname "$0")/.." || exit 1
MODE="${1:-}"

restore_switch() {
    sed -i '' 's/^AMAZON_WRITE_ENABLED=true/AMAZON_WRITE_ENABLED=false/' .env
    docker compose up -d --force-recreate api >/dev/null 2>&1
    sleep 10
    echo ""
    echo "--- writes disabled again ---"
    docker compose exec -T api python -c \
        "from app.config import settings; print('AMAZON_WRITE_ENABLED =', settings.amazon_write_enabled)"
}

if [ "$MODE" != "--confirm" ]; then
    echo "DRY RUN — nothing will be sent. Re-run with --confirm to create."
    docker compose exec -T -e PYTHONPATH=/app api \
        python /app/scripts/create_test_campaign.py
    exit $?
fi

if ! grep -q '^AMAZON_WRITE_ENABLED=' .env; then
    echo "ERROR: AMAZON_WRITE_ENABLED is missing from .env — aborting." >&2
    exit 1
fi

echo "--- enabling writes ---"
sed -i '' 's/^AMAZON_WRITE_ENABLED=false/AMAZON_WRITE_ENABLED=true/' .env
docker compose up -d --force-recreate api >/dev/null 2>&1
sleep 15

# Confirm the container really picked it up. Compose does not always reload
# env_file without --force-recreate, and a silent no-op here would be
# confusing rather than dangerous.
if ! docker compose exec -T api python -c \
        "import sys; from app.config import settings; sys.exit(0 if settings.amazon_write_enabled else 1)"; then
    echo "ERROR: the switch did not take effect in the container — aborting." >&2
    restore_switch
    exit 1
fi
echo "writes ENABLED"

echo ""
echo "--- creating campaign ---"
docker compose exec -T -e PYTHONPATH=/app api \
    python /app/scripts/create_test_campaign.py --confirm
RESULT=$?

restore_switch
exit "$RESULT"
