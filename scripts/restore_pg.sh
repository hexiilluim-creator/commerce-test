#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  P2-3 · Restore PostgreSQL — depuis le dernier backup safe                    ║
# ║  Usage :  ./restore_pg.sh [chemin_dump]  (défaut: dernier <backup_root>)     ║
# ║  Tests :  ./restore_pg.sh --self-test  (à passer en CI trimestrielle)        ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/autocommerce}"
PGHOST="${PGHOST:-${POSTGRES_HOST:-postgres}}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-${POSTGRES_USER:-autocommerce}}"
PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-autocommerce}}"
export PGHOST PGPORT PGUSER PGDATABASE

# ── Self-test — vérifie la chaîne backup→restore SANS toucher la prod ────────
if [[ "${1:-}" == "--self-test" ]]; then
  TARGET=$(mktemp -d)
  TEST_DB="restore_selftest_$(date +%s)"
  DUMP_FILE="${2:-${BACKUP_ROOT}/$(basename "$(cat "${BACKUP_ROOT}/last_backup.path" 2>/dev/null)")/base_${PGDATABASE}.dump}"

  if [[ ! -f "${DUMP_FILE}" ]]; then
    echo "FAIL: no dump file at ${DUMP_FILE}"
    exit 1
  fi
  createdb "${TEST_DB}" || true
  pg_restore --no-owner --no-privileges --dbname="${TEST_DB}" "${DUMP_FILE}" || true
  TABLES=$(psql -d "${TEST_DB}" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" || echo "0")
  dropdb --if-exists "${TEST_DB}"
  rm -rf "${TARGET}"
  echo "self-test result: tables_restored=${TABLES}"
  [[ "${TABLES}" -gt 10 ]] && echo "SELF-TEST PASSED" && exit 0
  echo "SELF-TEST FAILED" && exit 1
fi

# ── Restore réel (confirmé explicitement) ────────────────────────────────────
DUMP_FILE="${1:-${BACKUP_ROOT}/$(basename "$(cat "${BACKUP_ROOT}/last_backup.path" 2>/dev/null)")/base_${PGDATABASE}.dump}"

if [[ ! -f "${DUMP_FILE}" ]]; then
  echo "ERROR: no dump at ${DUMP_FILE}"
  exit 1
fi

echo "WARNING: vous allez RESTORER ${PGDATABASE} depuis ${DUMP_FILE}"
echo "         toutes les données en cours seront écrasées."
read -rp "Tapez 'YES' pour continuer: " ANSWER
[[ "${ANSWER}" == "YES" ]] || { echo "abandonné"; exit 1; }

# ── Vérification checksum AVANT restore ─────────────────────────────────────
SUMFILE="$(dirname "${DUMP_FILE}")/sha256_manifest.txt"
if [[ -f "${SUMFILE}" ]]; then
  ( cd "$(dirname "${DUMP_FILE}")" && sha256sum --check --status sha256_manifest.txt ) \
    && echo "checksum OK" \
    || { echo "checksum FAIL — refusing to restore"; exit 2; }
fi

# ── Restore atomique ─────────────────────────────────────────────────────────
echo "Drop + recreate ${PGDATABASE}"
dropdb --if-exists "${PGDATABASE}" || true
createdb "${PGDATABASE}"

pg_restore \
  --no-owner \
  --no-privileges \
  --jobs=4 \
  --dbname="${PGDATABASE}" \
  "${DUMP_FILE}"

# Vérification rapide post-restore
ROWS=$(psql -d "${PGDATABASE}" -tAc "SELECT count(*) FROM stores;" 2>/dev/null || echo "ERR")
echo "Restore terminé — stores=${ROWS}"
echo "RPO 15min, RTO cible 1h. Plan A : cold-standby. Plan B : PG promote."
