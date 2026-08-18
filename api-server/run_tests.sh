#!/bin/bash
# ============================================================
# run_tests.sh — AutoCommerce V13 Test Runner Enterprise
# ============================================================
# Usage:
#   ./run_tests.sh              # Tous les tests
#   ./run_tests.sh unit         # Tests unitaires uniquement
#   ./run_tests.sh integration  # Tests d'intégration uniquement
#   ./run_tests.sh security     # Tests de sécurité uniquement
#   ./run_tests.sh e2e          # Tests E2E uniquement
#   ./run_tests.sh db           # Tests DB async/sync uniquement
#   ./run_tests.sh monitoring   # Tests monitoring uniquement
# ============================================================

set -e

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   AutoCommerce V13 — Test Suite Enterprise       ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# Variables d'environnement pour les tests
export PYTEST_CURRENT_TEST=1
export DATABASE_URL="sqlite+aiosqlite:///:memory:"
export DISABLE_RATE_LIMIT=1
export JWT_SECRET_KEY="test-secret-key-for-ci-only"
export ENCRYPTION_KEY="AZPYERyizS47ts6PZg0c20NNKFyE_Cf0ygdCLbA90CI="
export WHATSAPP_ACCESS_TOKEN="test_wa_token"
export WHATSAPP_APP_SECRET="test_app_secret"
export WHATSAPP_VERIFY_TOKEN="test_verify_token"
export WHATSAPP_PHONE_NUMBER_ID="test_phone_id"
export OPENAI_API_KEY="sk-test-key"
export SKIP_LIMITER=1

MODE=${1:-"all"}

case "$MODE" in
    "unit")
        echo -e "${YELLOW}▶ Exécution des tests unitaires...${NC}"
        python -m pytest tests/unit/ -v --tb=short -m "not slow"
        ;;
    "integration")
        echo -e "${YELLOW}▶ Exécution des tests d'intégration...${NC}"
        python -m pytest tests/integration/ -v --tb=short
        ;;
    "security")
        echo -e "${YELLOW}▶ Exécution des tests de sécurité...${NC}"
        python -m pytest tests/integration/test_e2e_security.py -v --tb=short
        ;;
    "e2e")
        echo -e "${YELLOW}▶ Exécution des tests E2E...${NC}"
        python -m pytest tests/integration/test_e2e_business_flows.py tests/integration/test_e2e_flows.py -v --tb=short
        ;;
    "db")
        echo -e "${YELLOW}▶ Exécution des tests DB Async/Sync...${NC}"
        python -m pytest tests/unit/test_database_async_sync.py -v --tb=short
        ;;
    "monitoring")
        echo -e "${YELLOW}▶ Exécution des tests de monitoring...${NC}"
        python -m pytest tests/unit/test_monitoring.py -v --tb=short
        ;;
    "all")
        echo -e "${YELLOW}▶ Exécution de tous les tests...${NC}"
        python -m pytest tests/ -v --tb=short \
            --cov=. \
            --cov-report=term-missing \
            --cov-report=html:htmlcov \
            --ignore=tests/unit/test_omnicall_v9_pipeline.py
        ;;
    *)
        echo -e "${RED}Mode inconnu: $MODE${NC}"
        echo "Modes disponibles: unit, integration, security, e2e, db, monitoring, all"
        exit 1
        ;;
esac

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✅ Tous les tests ont réussi !${NC}"
else
    echo -e "${RED}❌ Des tests ont échoué (code: $EXIT_CODE)${NC}"
fi

exit $EXIT_CODE
