#!/bin/sh
# AutoCommerce V25 — Dev entrypoint
set -e

export SKIP_LIMITER=1
export DISABLE_RATE_LIMIT=1
export DEBUG=true
export ENV=development

cd "$(dirname "$0")"

echo "[run_python.sh] Running Alembic migrations..."
python3 -m alembic upgrade heads
echo "[run_python.sh] Migrations done."

echo "[run_python.sh] Running seed..."
python3 seed_production.py || true
echo "[run_python.sh] Seed done."

echo "[run_python.sh] Starting uvicorn on port ${PORT:-8000}..."
exec python3 -m uvicorn main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1 \
  --log-level info
