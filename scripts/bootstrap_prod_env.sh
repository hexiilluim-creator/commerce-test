#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_FILE="${1:-$ROOT_DIR/.env.prod}"
TEMPLATE_FILE="$ROOT_DIR/.env.prod.example"

if [[ -e "$TARGET_FILE" ]]; then
  echo "[bootstrap] Refus d'écraser $TARGET_FILE"
  echo "[bootstrap] Supprime-le ou passe un autre chemin si tu veux regénérer."
  exit 1
fi

cp "$TEMPLATE_FILE" "$TARGET_FILE"

mapfile -t GENERATED < <("$ROOT_DIR/scripts/generate_secrets.sh")

python3 - "$TARGET_FILE" "${GENERATED[@]}" <<'PY'
import sys
from pathlib import Path

target = Path(sys.argv[1])
updates = {}
for item in sys.argv[2:]:
    k, v = item.split("=", 1)
    updates[k] = v

lines = target.read_text().splitlines()
out = []
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    if key in updates:
        out.append(f"{key}={updates[key]}")
        continue
    if key == "DATABASE_URL":
        pwd = updates["POSTGRES_PASSWORD"]
        out.append(f"DATABASE_URL=postgresql+asyncpg://autocommerce:{pwd}@postgres:5432/autocommerce")
        continue
    if key in {"REDIS_URL", "REDIS_RATELIMIT_URL", "REDIS_CACHE_URL"}:
        pwd = updates["REDIS_PASSWORD"]
        suffix = {"REDIS_URL": "0", "REDIS_RATELIMIT_URL": "1", "REDIS_CACHE_URL": "2"}[key]
        out.append(f"{key}=redis://:{pwd}@redis:6379/{suffix}")
        continue
    out.append(line)

target.write_text("\n".join(out) + "\n")
PY

cat <<MSG
[bootstrap] Fichier créé : $TARGET_FILE
[bootstrap] Secrets générés : POSTGRES_PASSWORD, REDIS_PASSWORD, JWT_SECRET_KEY,
            ENCRYPTION_KEY, CSRF_SECRET, INTERNAL_HEALTH_TOKEN,
            INTERNAL_API_KEY, PROMETHEUS_INTERNAL_TOKEN,
            ADMIN_INITIAL_PASSWORD, SUPERADMIN_INITIAL_PASSWORD.
[bootstrap] À compléter manuellement avant déploiement : SERVER_DOMAIN, CORS_ORIGINS,
            clés LLM, éventuelles creds WhatsApp/S3/Stripe/Sentry.
MSG
