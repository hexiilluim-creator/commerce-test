#!/bin/sh
# start.sh — AutoCommerce V25 entrypoint
set -e

cd "$(dirname "$0")"

export PORT="${PORT:-8000}"
export UVICORN_WORKERS="${UVICORN_WORKERS:-4}"
LOG_LEVEL="$(echo "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"
export LOG_LEVEL

# IMPORTANT: SKIP_LIMITER must be "0" in production.
# Set SKIP_LIMITER=1 ONLY for local dev/CI to skip Redis rate-limit checks.
# Default: rate limiting ENABLED.
export SKIP_LIMITER="${SKIP_LIMITER:-0}"

echo "[start.sh] Running preflight checks..."
python3 preflight_check.py
echo "[start.sh] Preflight passed."

# V26 FIX (rapport §2.2) — Nettoyage défensif du port avant boot.
# --------------------------------------------------------------
# En dev / redeploy rapide, un ancien uvicorn peut n'avoir pas rendu le port.
# On libère proprement (SIGTERM 3 s, puis SIGKILL) au lieu de crasher avec
# `[Errno 98] address already in use`. Comportement désactivable en prod
# avec KILL_STALE_PORT=0 (recommandé quand un supervisor comme systemd/pm2
# gère déjà le cycle de vie).
KILL_STALE_PORT="${KILL_STALE_PORT:-1}"
if [ "$KILL_STALE_PORT" = "1" ]; then
  if command -v fuser >/dev/null 2>&1; then
    if fuser "${PORT}/tcp" >/dev/null 2>&1; then
      echo "[start.sh] Port ${PORT} busy — sending SIGTERM to stale process(es)..."
      fuser -k -TERM "${PORT}/tcp" || true
      sleep 3
      if fuser "${PORT}/tcp" >/dev/null 2>&1; then
        echo "[start.sh] Still busy — escalating to SIGKILL."
        fuser -k -KILL "${PORT}/tcp" || true
        sleep 1
      fi
    fi
  elif command -v lsof >/dev/null 2>&1; then
    _pids="$(lsof -ti tcp:${PORT} 2>/dev/null || true)"
    if [ -n "$_pids" ]; then
      echo "[start.sh] Port ${PORT} busy (pids: $_pids) — terminating..."
      # shellcheck disable=SC2086
      kill -TERM $_pids 2>/dev/null || true
      sleep 3
      _pids="$(lsof -ti tcp:${PORT} 2>/dev/null || true)"
      if [ -n "$_pids" ]; then
        # shellcheck disable=SC2086
        kill -KILL $_pids 2>/dev/null || true
        sleep 1
      fi
    fi
  fi
fi

# AUDIT-FIX: migrations couraient sans condition à chaque boot — sur un
# déploiement à plusieurs replicas (voir docker-compose.ha.yml), chaque
# instance retentait `alembic upgrade heads` en concurrence sur la même DB.
# Par défaut (1 instance, dev/staging) le comportement reste inchangé.
# Pour un déploiement multi-replica : mettre RUN_MIGRATIONS_ON_BOOT=0 sur le
# service API et exécuter les migrations une seule fois via un job dédié
# (voir le service `migrate` dans docker-compose.ha.yml).
RUN_MIGRATIONS_ON_BOOT="${RUN_MIGRATIONS_ON_BOOT:-1}"
if [ "$RUN_MIGRATIONS_ON_BOOT" = "1" ]; then
  echo "[start.sh] Running database migrations..."
  python3 -m alembic upgrade heads
  echo "[start.sh] Migrations complete. Starting uvicorn..."
else
  echo "[start.sh] RUN_MIGRATIONS_ON_BOOT=0 — skipping migrations (expecting a dedicated migrate job)."
fi

exec python3 -m uvicorn main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers "${UVICORN_WORKERS}" \
  --proxy-headers \
  --forwarded-allow-ips="${TRUSTED_PROXY_IPS:-127.0.0.1}" \
  --log-level "${LOG_LEVEL}"
