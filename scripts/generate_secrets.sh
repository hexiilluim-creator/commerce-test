#!/usr/bin/env bash
set -euo pipefail

hex32() {
  openssl rand -hex 32
}

strong_secret() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
}

fernet_key() {
  python3 - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
}

cat <<OUT
POSTGRES_PASSWORD=$(strong_secret)
REDIS_PASSWORD=$(strong_secret)
JWT_SECRET_KEY=$(hex32)
ENCRYPTION_KEY=$(fernet_key)
CSRF_SECRET=$(hex32)
INTERNAL_HEALTH_TOKEN=$(hex32)
INTERNAL_API_KEY=$(hex32)
PROMETHEUS_INTERNAL_TOKEN=$(hex32)
ADMIN_INITIAL_PASSWORD=$(strong_secret)
SUPERADMIN_INITIAL_PASSWORD=$(strong_secret)
OUT
