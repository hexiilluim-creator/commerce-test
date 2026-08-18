# AutoCommerce Enterprise V27.1 — Production hardening

## Ce qui a été ajouté / corrigé
1. **Nettoyage des `.env`**
   - suppression des secrets livrés en clair dans `api-server/.env` et `api-server/.env.production`
   - normalisation des exemples d'environnement
   - ajout d'un `.gitignore` pour empêcher les futurs commits de secrets

2. **Pack d'exploitation prod**
   - `scripts/generate_secrets.sh`
   - `scripts/bootstrap_prod_env.sh`
   - `scripts/check_compose_prod.sh`
   - `scripts/deploy_v27_1.sh`

3. **Documentation resserrée**
   - `DEPLOYMENT_V27_1.md`
   - `docs/production-checklist-v27.1.md`
   - `docs/deployment-strategy.md`

4. **Compose prod durci**
   - ajout du worker `celery` dédié
   - ajout de `read_only`, `tmpfs`, `cap_drop`, `no-new-privileges`, `pids_limit`
   - conservation de PostgreSQL / Redis sur loopback uniquement
   - chaîne `migrate` → `api`/`celery` imposée
