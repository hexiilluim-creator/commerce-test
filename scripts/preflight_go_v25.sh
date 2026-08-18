#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT_DIR/api-server"

echo "[preflight] AutoCommerce enterprise preflight"
test -f "$ROOT_DIR/docker-compose.prod.yml"
test -f "$ROOT_DIR/nginx.tls.conf"
test -f "$ROOT_DIR/.env.prod.example"
test -f "$API_DIR/tests/security/REPORT.md"
test -f "$API_DIR/tests/security/test_p0_p1_enterprise_controls.py"
# V28 : RLS géré par migrations Alembic (0058→0064), plus de fichier SQL standalone
echo "[preflight] required files present"
