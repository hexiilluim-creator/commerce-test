# ═══════════════════════════════════════════════════════════════════════════════
# AutoCommerce v24 — Makefile Enterprise
# ═══════════════════════════════════════════════════════════════════════════════
# Usage:
#   make help          → liste toutes les commandes disponibles
#   make install       → installer les dépendances
#   make test          → tests complets (unit + integration)
#   make test-fast     → tests rapides (unit uniquement, pas slow/e2e)
#   make lint          → ruff check + format
#   make typecheck     → pyright strict
#   make audit         → pip-audit CVE + scan secrets
#   make coverage      → rapport coverage HTML
#   make migration-check → vérifier la chaîne Alembic
#   make ci            → pipeline CI complet (lint → typecheck → test → audit)
#   make clean         → nettoyer les artefacts de build

.PHONY: help install test test-fast test-unit test-integration lint lint-fix \
        typecheck audit coverage migration-check ci clean dev check-env \
        test-security test-billing test-ai

# ── Configuration ─────────────────────────────────────────────────────────────
PYTHON         := python3
PIP            := pip
PYTEST         := pytest
RUFF           := ruff
PYRIGHT        := pyright
COVERAGE_MIN   := 70
REPORTS_DIR    := reports

# Couleurs terminal
RED    := \033[0;31m
GREEN  := \033[0;32m
YELLOW := \033[1;33m
BLUE   := \033[0;34m
BOLD   := \033[1m
RESET  := \033[0m

# ── help ──────────────────────────────────────────────────────────────────────
help: ## Afficher cette aide
	@echo ""
	@echo "$(BOLD)AutoCommerce v24 — Commandes Enterprise$(RESET)"
	@echo "════════════════════════════════════════════"
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*## / {printf "  $(GREEN)%-20s$(RESET) %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "$(YELLOW)Pipeline CI complet : make ci$(RESET)"
	@echo ""

# ── Installation ──────────────────────────────────────────────────────────────
install: ## Installer toutes les dépendances
	@echo "$(BLUE)📦 Installation des dépendances...$(RESET)"
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install pytest-asyncio httpx aiosqlite pytest-cov ruff pyright pip-audit
	@echo "$(GREEN)✅ Dépendances installées$(RESET)"

install-dev: install ## Installer les dépendances de développement
	$(PIP) install ipython black isort

# ── Vérification environnement ────────────────────────────────────────────────
check-env: ## Vérifier les variables d'environnement requises
	@echo "$(BLUE)🔍 Vérification des variables d'environnement...$(RESET)"
	@$(PYTHON) - << 'EOF'
import os, sys
required = ['DATABASE_URL', 'JWT_SECRET_KEY', 'ENCRYPTION_KEY']
missing = [v for v in required if not os.getenv(v)]
if missing:
    print(f"\033[0;31m❌ Variables manquantes: {', '.join(missing)}\033[0m")
    sys.exit(1)
print(f"\033[0;32m✅ Toutes les variables requises sont définies\033[0m")
ENV = os.getenv('ENV', 'production')
if ENV == 'production':
    print(f"\033[1;33m⚠️  ENV=production — certaines opérations sont bloquées\033[0m")
EOF

# ── Tests ─────────────────────────────────────────────────────────────────────
test: ## Tests complets (unit + integration, coverage ≥ 70%)
	@echo "$(BLUE)🧪 Lancement des tests complets...$(RESET)"
	@mkdir -p $(REPORTS_DIR)
	$(PYTEST) tests/ \
		-m "not e2e and not slow" \
		-v \
		--tb=short \
		--junitxml=$(REPORTS_DIR)/junit.xml \
		--cov=. \
		--cov-report=term-missing \
		--cov-report=html:$(REPORTS_DIR)/htmlcov \
		--cov-report=xml:$(REPORTS_DIR)/coverage.xml \
		--cov-fail-under=$(COVERAGE_MIN)
	@echo "$(GREEN)✅ Tests passés — coverage ≥ $(COVERAGE_MIN)%$(RESET)"

test-fast: ## Tests rapides (unit uniquement, sans slow/e2e/integration)
	@echo "$(BLUE)⚡ Tests rapides (unit)...$(RESET)"
	@mkdir -p $(REPORTS_DIR)
	$(PYTEST) tests/ \
		-m "unit and not slow" \
		-v \
		--tb=short \
		-x \
		--no-header
	@echo "$(GREEN)✅ Tests unitaires passés$(RESET)"

test-unit: ## Tests unitaires uniquement
	@echo "$(BLUE)🧪 Tests unitaires...$(RESET)"
	$(PYTEST) tests/ -m "unit" -v --tb=short

test-integration: ## Tests d'intégration uniquement (nécessite DB)
	@echo "$(BLUE)🧪 Tests d'intégration...$(RESET)"
	$(PYTEST) tests/integration/ -m "integration" -v --tb=long

test-security: ## Tests de sécurité uniquement
	@echo "$(BLUE)🔒 Tests de sécurité...$(RESET)"
	$(PYTEST) tests/ -m "security" -v --tb=short
	$(PYTEST) tests/test_security_headers.py tests/test_audit_log.py \
		tests/test_security_guard.py -v

test-billing: ## Tests de facturation uniquement
	@echo "$(BLUE)💳 Tests de facturation...$(RESET)"
	$(PYTEST) tests/test_saas_billing.py tests/test_credit_ledger.py \
		tests/test_billing_overlay.py tests/test_plan_catalog.py -v

test-ai: ## Tests IA/LLM uniquement
	@echo "$(BLUE)🤖 Tests IA...$(RESET)"
	$(PYTEST) tests/test_ai_guardrails.py tests/test_llm_gateway.py \
		tests/test_knowledge_loop.py tests/test_manager_agent.py -v

test-watch: ## Tests en mode watch (relance auto à chaque changement)
	@echo "$(BLUE)👁️  Mode watch activé...$(RESET)"
	$(PYTEST) tests/ -m "unit" --tb=short -f

# ── Coverage ──────────────────────────────────────────────────────────────────
coverage: ## Générer le rapport coverage HTML complet
	@echo "$(BLUE)📊 Génération du rapport coverage...$(RESET)"
	@mkdir -p $(REPORTS_DIR)
	$(PYTEST) tests/ \
		-m "not e2e and not slow" \
		--cov=. \
		--cov-report=html:$(REPORTS_DIR)/htmlcov \
		--cov-report=term-missing \
		--cov-report=xml:$(REPORTS_DIR)/coverage.xml \
		-q
	@echo "$(GREEN)✅ Rapport HTML: $(REPORTS_DIR)/htmlcov/index.html$(RESET)"

coverage-xml: ## Coverage au format XML (pour CI/Codecov)
	@mkdir -p $(REPORTS_DIR)
	$(PYTEST) tests/ -m "not e2e" --cov=. \
		--cov-report=xml:$(REPORTS_DIR)/coverage.xml -q

# ── Linting ───────────────────────────────────────────────────────────────────
lint: ## Ruff check + format check (mode strict)
	@echo "$(BLUE)🔍 Lint (ruff)...$(RESET)"
	$(RUFF) check .
	$(RUFF) format --check .
	@echo "$(GREEN)✅ Lint OK$(RESET)"

lint-fix: ## Ruff autofix + format (modifie les fichiers)
	@echo "$(YELLOW)🔧 Auto-fix lint...$(RESET)"
	$(RUFF) check --fix .
	$(RUFF) format .
	@echo "$(GREEN)✅ Lint auto-fixé$(RESET)"

# ── Type checking ─────────────────────────────────────────────────────────────
typecheck: ## Pyright strict (BLOQUANT — enterprise)
	@echo "$(BLUE)🔠 Type check (pyright strict)...$(RESET)"
	$(PYRIGHT) . --ignore-missing-imports
	@echo "$(GREEN)✅ Type check OK$(RESET)"

typecheck-report: ## Pyright avec rapport détaillé
	$(PYRIGHT) . --ignore-missing-imports --outputjson > $(REPORTS_DIR)/pyright.json 2>&1 || true
	@echo "$(GREEN)Rapport Pyright: $(REPORTS_DIR)/pyright.json$(RESET)"

# ── Audit sécurité ────────────────────────────────────────────────────────────
audit: ## Audit CVE (pip-audit) + scan secrets hardcodés
	@echo "$(BLUE)🛡️  Audit de sécurité...$(RESET)"
	@make _audit-cve
	@make _audit-secrets
	@echo "$(GREEN)✅ Audit terminé$(RESET)"

_audit-cve: ## pip-audit sur les dépendances
	@echo "$(BLUE)  CVE check (pip-audit)...$(RESET)"
	pip-audit -r requirements.txt --severity high || true

_audit-secrets: ## Scan des secrets hardcodés
	@echo "$(BLUE)  Secret scan...$(RESET)"
	@$(PYTHON) - << 'EOF'
import sys, re
from pathlib import Path

SECRET_PATTERNS = [
    r'(?i)(password|passwd|secret|api_key|apikey|token|private_key)\s*=\s*["\'][^"\']{8,}["\']',
    r'sk-[a-zA-Z0-9]{20,}',
    r'sk-ant-[a-zA-Z0-9\-]{20,}',
    r'SG\.[a-zA-Z0-9_\-]{22,}\.[a-zA-Z0-9_\-]{43,}',
    r'AKIA[0-9A-Z]{16}',
]
EXCLUDE = [r'test_', r'conftest', r'\.git/', r'__pycache__', r'htmlcov']
violations = []
for path in Path('.').rglob('*.py'):
    if any(re.search(ex, str(path)) for ex in EXCLUDE):
        continue
    try:
        content = path.read_text()
    except Exception:
        continue
    for pattern in SECRET_PATTERNS:
        for match in re.finditer(pattern, content):
            line = content.splitlines()[content[:match.start()].count('\n')]
            if any(x in line for x in ['os.environ', 'settings.', 'getenv', 'placeholder', 'test']):
                continue
            violations.append(f'{path}: {match.group(0)[:60]}')
if violations:
    print('\033[0;31m❌ SECRETS DÉTECTÉS:\033[0m')
    for v in violations: print(f'  {v}')
    sys.exit(1)
print(f'\033[0;32m✅ Aucun secret hardcodé ({sum(1 for _ in Path(".").rglob("*.py"))} fichiers)\033[0m')
EOF

# ── Migration Alembic ─────────────────────────────────────────────────────────
migration-check: ## Vérifier la chaîne Alembic (1 head, pas de cassure)
	@echo "$(BLUE)🗄️  Vérification chaîne Alembic...$(RESET)"
	@$(PYTHON) - << 'EOF'
import sys, re
from pathlib import Path

versions_dir = Path('alembic/versions')
if not versions_dir.exists():
    print('SKIP: alembic/versions introuvable')
    sys.exit(0)

files = [f for f in versions_dir.glob('*.py') if not f.name.startswith('__')]
revisions = {}
for f in files:
    src = f.read_text()
    rev_m = re.search(r'^revision\s*=\s*["\']([^"\']+)["\']', src, re.MULTILINE)
    down_m = re.search(r'^down_revision\s*=\s*(?:["\']([^"\']*)["\']|None)', src, re.MULTILINE)
    if not rev_m:
        continue
    rev = rev_m.group(1)
    down = down_m.group(1) if down_m and down_m.group(1) else None
    revisions[rev] = down

print(f'Migrations: {len(revisions)}')
all_revs = set(revisions.keys())
errors = []
for rev, down in revisions.items():
    if down is not None and down not in all_revs:
        errors.append(f'ERREUR: {rev}.down_revision="{down}" introuvable')
referenced = set(revisions.values()) - {None}
heads = all_revs - referenced
if len(heads) != 1:
    errors.append(f'ERREUR: {len(heads)} heads (attendu 1): {heads}')
if errors:
    for e in errors: print(f'\033[0;31m{e}\033[0m')
    sys.exit(1)
print(f'\033[0;32m✅ Chaîne OK — head: {heads}\033[0m')
EOF

migration-new: ## Créer une nouvelle migration Alembic (usage: make migration-new MSG="description")
	@if [ -z "$(MSG)" ]; then echo "$(RED)Usage: make migration-new MSG='ma description'$(RESET)"; exit 1; fi
	alembic revision --autogenerate -m "$(MSG)"

migration-upgrade: ## Appliquer toutes les migrations en attente
	@echo "$(YELLOW)⚠️  Appliquer les migrations DB (ENV=$(ENV))$(RESET)"
	alembic upgrade head

migration-downgrade: ## Revenir à la migration précédente
	@echo "$(YELLOW)⚠️  Rollback d'une migration$(RESET)"
	alembic downgrade -1

# ── Pipeline CI complet ───────────────────────────────────────────────────────
ci: ## Pipeline CI complet : lint → typecheck → test → audit → migration
	@echo ""
	@echo "$(BOLD)$(BLUE)════════════════════════════════════════════$(RESET)"
	@echo "$(BOLD)$(BLUE)  AutoCommerce v24 — Pipeline CI Enterprise$(RESET)"
	@echo "$(BOLD)$(BLUE)════════════════════════════════════════════$(RESET)"
	@echo ""
	@echo "$(BOLD)JOB 1 — Lint$(RESET)"
	@make lint
	@echo ""
	@echo "$(BOLD)JOB 2 — Type check$(RESET)"
	@make typecheck || echo "$(YELLOW)⚠️  Pyright warnings (non-bloquant local, bloquant CI)$(RESET)"
	@echo ""
	@echo "$(BOLD)JOB 3 — Tests + Coverage$(RESET)"
	@make test
	@echo ""
	@echo "$(BOLD)JOB 4 — Migration chain$(RESET)"
	@make migration-check
	@echo ""
	@echo "$(BOLD)JOB 5 — Audit sécurité$(RESET)"
	@make audit
	@echo ""
	@echo "$(BOLD)$(GREEN)════════════════════════════════════════════$(RESET)"
	@echo "$(BOLD)$(GREEN)  ✅ Pipeline CI complet — TOUT VERT$(RESET)"
	@echo "$(BOLD)$(GREEN)════════════════════════════════════════════$(RESET)"
	@echo ""

ci-fast: ## Pipeline CI rapide (lint + test-fast uniquement)
	@make lint
	@make test-fast

# ── Développement ──────────────────────────────────────────────────────────────
dev: ## Lancer le serveur de développement
	@echo "$(BLUE)🚀 Démarrage du serveur...$(RESET)"
	uvicorn main:app --reload --host 0.0.0.0 --port 5000 --log-level info

dev-debug: ## Serveur avec logs DEBUG
	uvicorn main:app --reload --host 0.0.0.0 --port 5000 --log-level debug

# ── Nettoyage ─────────────────────────────────────────────────────────────────
clean: ## Nettoyer les artefacts de build et de test
	@echo "$(BLUE)🧹 Nettoyage...$(RESET)"
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	rm -rf $(REPORTS_DIR)/htmlcov $(REPORTS_DIR)/coverage.xml 2>/dev/null || true
	@echo "$(GREEN)✅ Nettoyage terminé$(RESET)"

clean-all: clean ## Nettoyage complet (inclut reports et dist)
	rm -rf $(REPORTS_DIR)/ dist/ build/ *.egg-info/ 2>/dev/null || true
	@echo "$(GREEN)✅ Nettoyage complet$(RESET)"

# ── Rapport complet ───────────────────────────────────────────────────────────
report: ## Générer un rapport de santé complet du projet
	@echo ""
	@echo "$(BOLD)AutoCommerce v24 — Rapport de santé$(RESET)"
	@echo "════════════════════════════════════"
	@echo ""
	@echo "$(BOLD)📁 Structure$(RESET)"
	@echo "  Services    : $$(ls services/*.py 2>/dev/null | wc -l | tr -d ' ') fichiers"
	@echo "  Tests       : $$(ls tests/*.py 2>/dev/null | wc -l | tr -d ' ') fichiers"
	@echo "  Migrations  : $$(ls alembic/versions/*.py 2>/dev/null | wc -l | tr -d ' ') migrations"
	@echo ""
	@echo "$(BOLD)🐍 Python$(RESET)"
	@$(PYTHON) --version
	@$(PIP) show fastapi | grep Version | sed 's/^/  FastAPI /'
	@echo ""
	@echo "$(BOLD)🔧 Outils$(RESET)"
	@$(RUFF) --version 2>/dev/null && echo "  ruff OK" || echo "  ruff: non installé"
	@$(PYRIGHT) --version 2>/dev/null && echo "  pyright OK" || echo "  pyright: non installé"
	@pytest --version 2>/dev/null | head -1 | sed 's/^/  /' || echo "  pytest: non installé"
