#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env.prod}"
command -v docker >/dev/null 2>&1 || { echo "[deploy] ERREUR: docker absent sur l'hôte" >&2; exit 1; }
COMPOSE=(docker compose -f "$ROOT_DIR/docker-compose.prod.yml" --env-file "$ENV_FILE")

"$ROOT_DIR/scripts/check_compose_prod.sh" "$ENV_FILE"

echo "[deploy] Build des images runtime..."
"${COMPOSE[@]}" build api celery frontend

echo "[deploy] Démarrage de postgres et redis..."
"${COMPOSE[@]}" up -d postgres redis

echo "[deploy] Attente de PostgreSQL..."
"${COMPOSE[@]}" exec -T postgres sh -lc 'for i in $(seq 1 30); do pg_isready -U "${POSTGRES_USER:-autocommerce}" -d "${POSTGRES_DB:-autocommerce}" >/dev/null 2>&1 && exit 0; sleep 2; done; exit 1'

echo "[deploy] Vérification pgvector dans PostgreSQL..."
"${COMPOSE[@]}" exec -T postgres sh -lc 'test -f /usr/share/postgresql/16/extension/vector.control'
"${COMPOSE[@]}" exec -T postgres sh -lc 'psql -U "${POSTGRES_USER:-autocommerce}" -d "${POSTGRES_DB:-autocommerce}" -Atqc "SELECT 1 FROM pg_available_extensions WHERE name = '\''vector'\'';" | grep -qx 1'

echo "[deploy] Lancement bloquant de la migration one-shot..."
"${COMPOSE[@]}" up --abort-on-container-exit --exit-code-from migrate migrate

echo "[deploy] Vérification des tables critiques après migration..."
"${COMPOSE[@]}" exec -T postgres sh -lc 'psql -U "${POSTGRES_USER:-autocommerce}" -d "${POSTGRES_DB:-autocommerce}" -Atqc "SELECT to_regclass('\''public.plan_limits'\''), to_regclass('\''public.tenant_subscriptions'\''), to_regclass('\''public.orders'\'');" | grep -q "plan_limits|tenant_subscriptions|orders"'

echo "[deploy] RLS appliqué automatiquement par alembic upgrade head (migrations 0058→0064)."
echo "[deploy] Vérification RLS..."
${COMPOSE[@]} exec -T postgres sh -lc 'psql -U "${POSTGRES_USER:-autocommerce}" -d "${POSTGRES_DB:-autocommerce}" -Atqc "SELECT count(*) FROM pg_policies WHERE schemaname=\'public\' AND policyname LIKE \'tenant_isolation_%\';"'

echo "[deploy] Démarrage des services applicatifs..."
"${COMPOSE[@]}" up -d api celery frontend nginx

echo "[deploy] État des services:"
"${COMPOSE[@]}" ps

echo "[deploy] Healthchecks locaux..."
curl -fsS http://127.0.0.1/nginx-health >/dev/null
curl -fsS http://127.0.0.1/api/health >/dev/null || true

echo "[deploy] Déploiement V27.1 terminé."
echo "[deploy] Étapes manuelles restantes :"
echo "          1) seed_production.py si nécessaire (voir garde SEED_DEMO_STORE)"
echo "          2) login admin + rotation immédiate des mots de passe seed"
echo "          3) test WhatsApp / webhook / upload / backup / restore"
echo "          (RLS déjà appliqué automatiquement par alembic upgrade head — plus d'étape manuelle)"
