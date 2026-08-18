    #!/usr/bin/env bash
    set -euo pipefail

    ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    ENV_FILE="${1:-$ROOT_DIR/.env.prod}"
    COMPOSE_FILE="$ROOT_DIR/docker-compose.prod.yml"
    EXAMPLE_FILE="$ROOT_DIR/.env.prod.example"

    fail() {
      echo "[check] ERREUR: $*" >&2
      exit 1
    }

    [[ -f "$COMPOSE_FILE" ]] || fail "docker-compose.prod.yml introuvable"
    [[ -f "$ENV_FILE" ]] || fail "fichier d'environnement introuvable: $ENV_FILE"
    [[ -f "$EXAMPLE_FILE" ]] || fail ".env.prod.example introuvable"

    required_keys=(
      POSTGRES_PASSWORD
      REDIS_PASSWORD
      JWT_SECRET_KEY
      ENCRYPTION_KEY
      CSRF_SECRET
      INTERNAL_HEALTH_TOKEN
      INTERNAL_API_KEY
      PROMETHEUS_INTERNAL_TOKEN
    )
    for key in "${required_keys[@]}"; do
      grep -Eq "^${key}=" "$ENV_FILE" || fail "${key} absent"
    done

    if grep -E '(^|=)(GENERATE_|https://api\.example\.com|https://app\.example\.com|https://www\.example\.com)' "$ENV_FILE" >/dev/null; then
      fail "des valeurs de bootstrap restent dans $ENV_FILE"
    fi

    if grep -E 'sk-|AKIA|ghp_|AIza|eyJ[0-9A-Za-z._-]+' "$ENV_FILE" >/dev/null; then
      fail "séquence ressemblant à un secret embarqué détectée dans $ENV_FILE"
    fi

    python3 - "$ENV_FILE" "$EXAMPLE_FILE" <<'PY'
import re
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
example_path = Path(sys.argv[2])
secret_keys = {
    'POSTGRES_PASSWORD', 'REDIS_PASSWORD', 'JWT_SECRET_KEY', 'ENCRYPTION_KEY',
    'CSRF_SECRET', 'INTERNAL_HEALTH_TOKEN', 'INTERNAL_API_KEY',
    'PROMETHEUS_INTERNAL_TOKEN', 'ADMIN_INITIAL_PASSWORD', 'SUPERADMIN_INITIAL_PASSWORD'
}

def parse(path: Path):
    data = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line or line.lstrip().startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        data[k.strip()] = v.strip()
    return data

env = parse(env_path)
example = parse(example_path)
missing = sorted(set(example) - set(env))
if missing:
    raise SystemExit(f"[check] ERREUR: clés manquantes dans {env_path.name}: {', '.join(missing)}")

for key in secret_keys:
    if key in env and key in example and env[key] == example[key]:
        raise SystemExit(f"[check] ERREUR: la clé {key} n'a pas été régénérée (identique à l'exemple)")

print('[check] diff example/env: OK')
PY

    grep -q '127.0.0.1:5432:5432' "$COMPOSE_FILE" || fail "PostgreSQL doit rester lié à 127.0.0.1"
    grep -q '127.0.0.1:6379:6379' "$COMPOSE_FILE" || fail "Redis doit rester lié à 127.0.0.1"
    grep -q 'service_completed_successfully' "$COMPOSE_FILE" || fail "chaînage migrate -> api/celery absent"
    grep -q 'no-new-privileges:true' "$COMPOSE_FILE" || fail "no-new-privileges absent"
    grep -q 'read_only: true' "$COMPOSE_FILE" || fail "read_only absent sur les services durcis"
    grep -q 'ac_celery' "$COMPOSE_FILE" || fail "worker celery absent du compose prod"

    if command -v docker >/dev/null 2>&1; then
      docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" config -q
    else
      python3 - "$COMPOSE_FILE" <<'PY'
import sys
import yaml
from pathlib import Path
compose = Path(sys.argv[1])
data = yaml.safe_load(compose.read_text(encoding="utf-8"))
if not isinstance(data, dict) or "services" not in data:
    raise SystemExit("[check] ERREUR: fichier compose invalide")
print("[check] docker absent -> validation YAML fallback OK")
PY
    fi

    echo "[check] OK: environnement et compose prod cohérents"
