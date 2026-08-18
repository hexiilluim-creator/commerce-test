#!/usr/bin/env bash
# =============================================================================
# scripts/release_gate.sh — Gate bloquant avant release enterprise V28
# =============================================================================
# Usage : bash scripts/release_gate.sh [chemin]
# Exit 0 = OK, Exit 1 = problème bloquant
# =============================================================================
set -euo pipefail

TARGET="${1:-.}"
ERRORS=0
WARNINGS=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo "======================================="
echo " AutoCommerce Release Gate — V28"
echo " Cible : $TARGET"
echo "======================================="

# ── 1. Fichiers .env peuplés de SECRETS (hors frontend non-sensible) ──────────
echo ""
echo "── [1/4] Scan .env avec secrets réels ──────────────────────────────────"

SECRET_KEYS_PATTERN="^(POSTGRES_PASSWORD|REDIS_PASSWORD|JWT_SECRET_KEY|ENCRYPTION_KEY|CSRF_SECRET|INTERNAL_API_KEY|INTERNAL_HEALTH_TOKEN|PROMETHEUS_INTERNAL_TOKEN|ADMIN_INITIAL_PASSWORD|SUPERADMIN_INITIAL_PASSWORD|WHATSAPP_APP_SECRET|WHATSAPP_VERIFY_TOKEN|INSTAGRAM_APP_SECRET|FACEBOOK_APP_SECRET|STRIPE_SECRET_KEY)=.+"
PLACEHOLDER_PATTERN="CH""ANGE_ME|change-me|GENERATE_|dev-secret|dev-csrf|replace-with|REPLACE_WITH|your_|<.*>|example|placeholder|min_32"

ENV_ERRORS=0
while IFS= read -r file; do
  # Exclure tous les .example
  [[ "$file" == *.example* ]] && continue
  [[ "$file" == *.example ]] && continue

  # Chercher des clés sensibles avec des valeurs non-placeholder
  HITS=$(grep -E "$SECRET_KEYS_PATTERN" "$file" 2>/dev/null | grep -vE "$PLACEHOLDER_PATTERN" || true)
  if [ -n "$HITS" ]; then
    echo -e "  ${RED}✗ FAIL${NC} Secret réel dans : $file"
    echo "$HITS" | sed 's/=.*/=***/' | head -5
    ENV_ERRORS=$((ENV_ERRORS + 1))
    ERRORS=$((ERRORS + 1))
  fi
done < <(find "$TARGET" \( -name ".env" -o -name ".env.*" -o -name "*.env" \) -type f 2>/dev/null)

[ $ENV_ERRORS -eq 0 ] && echo -e "  ${GREEN}✓ Aucun secret réel dans les .env${NC}"

# ── 2. Scan valeurs sensibles dans .env* (double vérification) ─────────────────
echo ""
echo "── [2/4] Double vérification .env* ─────────────────────────────────────"
REAL_SECRETS=$(find "$TARGET" \( -name ".env" -o -name ".env.*" \) -type f 2>/dev/null \
  | grep -v "\.example" \
  | xargs grep -lE "$SECRET_KEYS_PATTERN" 2>/dev/null \
  | while read -r f; do
      grep -E "$SECRET_KEYS_PATTERN" "$f" | grep -vE "$PLACEHOLDER_PATTERN" && echo "FILE:$f"
    done || true)

if [ -z "$REAL_SECRETS" ]; then
  echo -e "  ${GREEN}✓ Aucune valeur sensible non-placeholder${NC}"
else
  echo -e "  ${RED}✗ FAIL${NC} Valeurs sensibles détectées"
  echo "$REAL_SECRETS"
  ERRORS=$((ERRORS + 1))
fi

# ── 3. Secrets hardcodés dans le code source ───────────────────────────────────
echo ""
echo "── [3/4] Scan secrets hardcodés (code source) ───────────────────────────"

CODE_ERRORS=0
# Tokens Stripe live
while IFS= read -r match; do
  [[ "$match" =~ test ]] && continue
  echo -e "  ${RED}✗ FAIL${NC} Token Stripe LIVE : $match"
  CODE_ERRORS=$((CODE_ERRORS+1)); ERRORS=$((ERRORS+1))
done < <(grep -rn "sk_live_[a-zA-Z0-9]\{20,\}" "$TARGET" \
  --include="*.py" --include="*.ts" --include="*.js" --include="*.env" 2>/dev/null \
  | grep -v "__pycache__\|node_modules" || true)

# JWT hardcodés (longueur significative, pas dans des tests ou commentaires)
while IFS= read -r match; do
  line="${match#*:*:}"
  [[ "$line" =~ "#" ]] && continue
  [[ "$line" =~ "getenv\|environ\|settings\.\|os\." ]] && continue
  [[ "$match" =~ "test\|spec\|mock\|example\|CH""ANGE_ME\|RGPD_DELETED" ]] && continue
  echo -e "  ${RED}✗ FAIL${NC} Secret potentiellement hardcodé : ${match%%:*}"
  CODE_ERRORS=$((CODE_ERRORS+1)); ERRORS=$((ERRORS+1))
done < <(grep -rn "password\s*=\s*['\"][^'\"]\{12,\}['\"]" "$TARGET" \
  --include="*.py" --include="*.js" --include="*.ts" 2>/dev/null \
  | grep -v "__pycache__\|node_modules\|RGPD_DELETED\|hashed_password\|test_\|_test\.\|spec\.\|mock\|CH""ANGE_ME\|dev-" || true)

[ $CODE_ERRORS -eq 0 ] && echo -e "  ${GREEN}✓ Aucun secret hardcodé détecté${NC}"

# ── 4. Présence des .example requis ───────────────────────────────────────────
echo ""
echo "── [4/4] Présence des .example ─────────────────────────────────────────"
for f in ".env.prod.example" "source/api-server/.env.example" "source/api-server/.env.production.example"; do
  if [ -f "$TARGET/$f" ]; then
    echo -e "  ${GREEN}✓ OK${NC}  $f"
  else
    echo -e "  ${YELLOW}⚠ WARN${NC} $f manquant"
    WARNINGS=$((WARNINGS+1))
  fi
done

# ── Résultat ───────────────────────────────────────────────────────────────────
echo ""
echo "======================================="
if [ $ERRORS -eq 0 ]; then
  echo -e " ${GREEN}PASS${NC} — Release gate OK (0 erreur, $WARNINGS warning)"
  echo "======================================="
  exit 0
else
  echo -e " ${RED}FAIL${NC} — $ERRORS erreur(s) bloquante(s), $WARNINGS warning(s)"
  echo " → Ne pas distribuer avant correction"
  echo "======================================="
  exit 1
fi
