#!/usr/bin/env bash
#
# Run the frontend's PRODUCTION build locally, before pushing.
#
#   bash scripts/verify-frontend-build.sh
#
# Why this exists: `next dev` and `tsc --noEmit` both pass on code that `next
# build` rejects. The gap is prerendering. A client component calling
# useSearchParams() needs a Suspense boundary above it, and only the production
# build enforces that — so five screens shipped green locally and failed on the
# server, after a nine-minute Docker build.
#
# It builds into /tmp inside the container, never /app/.next, because building in
# place overwrites the dev server's output and leaves the local app broken until
# it is restarted. That has happened here before.
set -euo pipefail

COMPOSE="docker compose"
say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

[[ -f docker-compose.yml ]] || { echo "Run from the ppc-os directory." >&2; exit 1; }

say "Type check"
$COMPOSE exec -T frontend npx tsc --noEmit

say "Production build (isolated from the dev server's .next)"
$COMPOSE exec -T frontend sh -c '
set -e
rm -rf /tmp/prodbuild && mkdir -p /tmp/prodbuild
cd /app && tar cf - --exclude=./node_modules --exclude=./.next . | tar xf - -C /tmp/prodbuild
ln -s /app/node_modules /tmp/prodbuild/node_modules
cd /tmp/prodbuild && npm run build
'

say "Cleaning up"
$COMPOSE exec -T frontend rm -rf /tmp/prodbuild

echo
echo "Production build passes. Safe to push and deploy."
