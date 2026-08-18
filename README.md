# AutoCommerce Enterprise V28

Plateforme SaaS omnicanale orientée retail / aftermarket avec backend FastAPI, frontend React/Vite, worker Celery, observabilité et pack Docker/Compose durci pour la production.

## Contenu utile du package
- `api-server/` : backend FastAPI, migrations, seed, tests.
- `autocommerce-app/` : frontend React/Vite.
- `scripts/` : génération de secrets, bootstrap `.env.prod`, contrôle compose, déploiement.
- `docs/` : stratégie de déploiement et checklist de prod.
- `docs/archive/` : changelogs et rapports des versions précédentes (V26 → V27.1) — voir `CHANGELOG.md` à la racine pour l'index.
- `docker-compose.prod.yml` : stack monoserveur durcie.
- `.env.prod.example` : template officiel de production.

## Flux recommandé
1. `bash scripts/bootstrap_prod_env.sh`
2. compléter `.env.prod`
3. `bash scripts/check_compose_prod.sh .env.prod`
4. `bash scripts/deploy_v27_1.sh .env.prod`
5. `docker compose -f docker-compose.prod.yml --env-file .env.prod exec api python3 seed_production.py`

## Livrables de cette phase
- `CHANGES_V28.md`
- `CHANGELOG.md` (index de toutes les versions)
- `VERSION`

