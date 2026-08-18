#!/usr/bin/env bash
# ============================================================
# run_regression.sh — AutoCommerce V25 Regression Test Suite
# ============================================================
# Usage:
#   bash run_regression.sh          # targeted suite (smoke / PR ciblée)
#   bash run_regression.sh --smoke  # targeted suite explicite
#   bash run_regression.sh --full   # suite complète avec gate coverage 55%
# ============================================================

set -euo pipefail

REPORTS_DIR="reports"
mkdir -p "${REPORTS_DIR}"

PROFILE="pytest.ini"
LABEL="Targeted suite — sécurité + webhook"
declare -a TEST_TARGETS=(
  "tests/test_security_headers.py"
  "tests/test_security_guard.py"
  "tests/test_security_multitenant.py"
  "tests/test_webhook_reliability.py"
)

case "${1:-}" in
  ""|--smoke)
    ;;
  --full)
    PROFILE="pytest_full.ini"
    LABEL="Full suite — gate coverage 55%"
    TEST_TARGETS=("tests")
    ;;
  *)
    echo "Usage: bash run_regression.sh [--smoke|--full]" >&2
    exit 2
    ;;
esac

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   AutoCommerce V25 — Regression Suite                   ║"
echo "║   ${LABEL}"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

export PYTEST_CURRENT_TEST=1
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///:memory:}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-ci-test-only-not-for-prod}"
export ENCRYPTION_KEY="${ENCRYPTION_KEY:-AZPYERyizS47ts6PZg0c20NNKFyE_Cf0ygdCLbA90CI=}"
export WHATSAPP_ACCESS_TOKEN="${WHATSAPP_ACCESS_TOKEN:-ci_token}"
export WHATSAPP_APP_SECRET="${WHATSAPP_APP_SECRET:-ci_secret}"
export WHATSAPP_VERIFY_TOKEN="${WHATSAPP_VERIFY_TOKEN:-ci_verify}"
export WHATSAPP_PHONE_NUMBER_ID="${WHATSAPP_PHONE_NUMBER_ID:-ci_phone_id}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-sk-ci-test}"
export DISABLE_RATE_LIMIT=1
export INTERNAL_HEALTH_TOKEN="${INTERNAL_HEALTH_TOKEN:-ci-health-token}"

python3 -m pytest \
  -c "${PROFILE}" \
  "${TEST_TARGETS[@]}" \
  --junitxml="${REPORTS_DIR}/regression_$(date +%Y%m%d_%H%M%S).xml" \
  -p no:cacheprovider \
  2>&1 | tee "${REPORTS_DIR}/regression_last.log"

EXIT_CODE=${PIPESTATUS[0]}

echo ""
if [ "${EXIT_CODE}" -eq 0 ]; then
  echo "✅  SUITE PASSÉE — profil ${PROFILE} validé"
else
  echo "❌  TESTS ÉCHOUÉS (exit=${EXIT_CODE}) — Corriger avant déploiement"
fi
echo ""
exit "${EXIT_CODE}"
