#!/bin/sh
set -e

echo "[entrypoint] running migrations..."
alembic upgrade head

echo "[entrypoint] seeding users (idempotent)..."
python -m app.modules.auth.seed

echo "[entrypoint] starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info
