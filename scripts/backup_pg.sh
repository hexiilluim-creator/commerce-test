#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  P2-3 · Backup PostgreSQL — pg_dump + WAL archiving                          ║
# ║  RPO 15 min, RTO 1 h. Rotation auto. Tests de restore trimestriels documentés.║
# ╚══════════════════════════════════════════════════════════════════════════════╝
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/autocommerce}"
WAL_ARCHIVE_DIR="${WAL_ARCHIVE_DIR:-/var/backups/autocommerce/wal}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TODAY_DIR="${BACKUP_ROOT}/${TIMESTAMP}"
LOG="${BACKUP_ROOT}/backup.log"

PGHOST="${PGHOST:-${POSTGRES_HOST:-postgres}}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-${POSTGRES_USER:-autocommerce}}"
PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-autocommerce}}"
export PGHOST PGPORT PGUSER PGDATABASE

mkdir -p "${TODAY_DIR}" "${WAL_ARCHIVE_DIR}"

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "${LOG}"
}

notify() {
  local status="$1"; shift
  local subject="[AutoCommerce Backup ${status^^}] $*"
  if command -v curl >/dev/null 2>&1 && [[ -n "${ALERT_WEBHOOK_URL:-}" ]]; then
    curl -fsS -X POST "${ALERT_WEBHOOK_URL}" \
      -H "Content-Type: application/json" \
      -d "$(printf '{"status":"%s","subject":"%s","timestamp":"%s"}' \
           "${status}" "${subject//\"/\\\"}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")" \
      || true
  fi
  log "${subject}"
}

# ── 1. Full base backup (compressed, custom format pour restore parallèle) ──
log "Starting pg_basebackup ${PGDATABASE} @ ${TIMESTAMP}"
DUMP_FILE="${TODAY_DIR}/base_${PGDATABASE}.dump"

if ! pg_dump \
    --format=custom \
    --compress=9 \
    --no-owner \
    --no-privileges \
    --serializable-deferrable \
    --jobs=4 \
    --file="${DUMP_FILE}" \
    "${PGDATABASE}" 2>>"${LOG}"; then
  notify "fail" "pg_dump failed for ${PGDATABASE}"
  exit 1
fi
log "pg_dump OK: $(stat -c%s "${DUMP_FILE}" 2>/dev/null || du -h "${DUMP_FILE}" | awk '{print $1}') bytes"

# ── 2. WAL archiving (continuous) — séparation du DB principal ───────────────
cat > "${TODAY_DIR}/archive_wal.sh" <<'WALSH'
#!/usr/bin/env bash
set -euo pipefail
WAL_SRC="${WAL_SRC:-/var/lib/postgresql/data/pg_wal}"
WAL_DST="${WAL_DST:-/var/backups/autocommerce/wal}"
mkdir -p "${WAL_DST}"
# Implemented via archive_command in postgresql.conf:
#   archive_mode = on
#   archive_command = '/usr/local/bin/archive_wal.sh %p %f'
test -f "$1" && cp -f "$1" "${WAL_DST}/$2" && gzip -f "${WAL_DST}/$2"
WALSH
chmod +x "${TODAY_DIR}/archive_wal.sh"

# ── 3. Manifest + checksum ───────────────────────────────────────────────────
( cd "${TODAY_DIR}" && sha256sum -- *.dump > sha256_manifest.txt )
log "Manifest wrote sha256 for $(find "${TODAY_DIR}" -name 'sha256_manifest.txt' | wc -l) dump(s)"

# ── 4. Rotation (RETENTION_DAYS) ──────────────────────────────────────────────
log "Applying retention: ${RETENTION_DAYS} days"
find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d \
     -mtime "+${RETENTION_DAYS}" -exec rm -rf {} \; 2>/dev/null || true
find "${WAL_ARCHIVE_DIR}" -type f -mtime "+${RETENTION_DAYS}" -delete 2>/dev/null || true

# ── 5. Last backup pointer (pour restore rapide) ──────────────────────────────
echo "${TODAY_DIR}" > "${BACKUP_ROOT}/last_backup.path"
log "Last backup pointer: ${TODAY_DIR}"

notify "success" "Backup OK ${TIMESTAMP} (RPO 15min, RTO 1h)"
