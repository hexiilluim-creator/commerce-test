#!/bin/sh
# start_dev.sh — AutoCommerce V25 démarrage DÉVELOPPEMENT
# Usage: bash start_dev.sh
# Note: Ne lance PAS le preflight check strict (ENV=development)
set -e

cd "$(dirname "$0")"

# Load .env if it exists using a more robust method
if [ -f ".env" ]; then
    # Use python to export variables to avoid shell parsing issues with spaces
    # This creates a temporary file with export commands and sources it
    python3 -c "
import os
from pathlib import Path
env_path = Path('.env')
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            key, val = line.split('=', 1)
            # Remove quotes if present
            if (val.startswith('\"') and val.endswith('\"')) or (val.startswith(\"'\") and val.endswith(\"'\")):
                val = val[1:-1]
            print(f'export {key}=\"{val}\"')
" > .env.exported
    . ./.env.exported
    rm .env.exported
fi

export ENV="${ENV:-development}"
export DEBUG="${DEBUG:-True}"
export PORT="${PORT:-8000}"
export UVICORN_WORKERS=1
export SKIP_LIMITER="${SKIP_LIMITER:-1}"
export LOG_LEVEL="${LOG_LEVEL:-debug}"

echo "[start_dev.sh] ENV=$ENV DEBUG=$DEBUG PORT=$PORT"
echo "[start_dev.sh] Running migrations..."
python3 -m alembic upgrade heads
echo "[start_dev.sh] Migrations done."

exec python3 -m uvicorn main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers 1 \
  --reload \
  --log-level "${LOG_LEVEL}"
