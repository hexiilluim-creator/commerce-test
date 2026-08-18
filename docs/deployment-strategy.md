# AutoCommerce Enterprise V27.1 — Stratégie de déploiement

## Cible recommandée
- 1 hôte Docker/Compose pour le premier palier production.
- Reverse proxy Nginx en frontal.
- PostgreSQL et Redis sur volumes persistants.
- `migrate` exécuté une seule fois avant l'API.
- `celery` séparé de l'API pour les tâches asynchrones.

## Séquence recommandée
1. Générer `.env.prod` avec `scripts/bootstrap_prod_env.sh`.
2. Compléter les variables métier / domaines / intégrations.
3. Exécuter `scripts/check_compose_prod.sh`.
4. Exécuter `scripts/deploy_v27_1.sh`.
5. Lancer la recette fonctionnelle minimale.
6. Activer monitoring, backup et rotation des secrets.

## Garde-fous V27.1
- fichiers `.env` sanitisés dans le package livré
- compose prod avec worker Celery dédié
- `read_only`, `tmpfs`, `cap_drop`, `no-new-privileges`
- exposition loopback uniquement pour PostgreSQL/Redis
- migration one-shot avant API/worker
