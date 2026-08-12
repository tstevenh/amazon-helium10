#!/bin/sh
# Nightly Postgres dump. Keeps 14 days. Run from the compose project root.
#
# Consolidating onto one server removes the accidental redundancy of every
# teammate holding their own local copy, so this is required, not optional.
#
# Cron (on the server, not a laptop):
#   0 3 * * * cd /opt/ppc-os && ./scripts/backup-db.sh >> /var/log/ppc-os-backup.log 2>&1
set -eu

BACKUP_DIR="${BACKUP_DIR:-/var/backups/ppc-os}"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/ppc-os-$STAMP.dump"
mkdir -p "$BACKUP_DIR"

docker compose exec -T postgres pg_dump \
  -U "${POSTGRES_USER:-ppc_os}" \
  -d "${POSTGRES_DB:-ppc_os}" \
  --format=custom > "$OUT"

# Fail loudly if the dump is suspiciously small. An empty dump that quietly
# rotates away the good ones is worse than no backup at all.
SIZE=$(wc -c < "$OUT")
if [ "$SIZE" -lt 10000 ]; then
  echo "ERROR: dump is only ${SIZE} bytes — check the database" >&2
  exit 1
fi

find "$BACKUP_DIR" -name 'ppc-os-*.dump' -mtime +14 -delete
echo "backup ok: $OUT (${SIZE} bytes)"
