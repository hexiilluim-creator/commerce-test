# Onboarding technique

## Prérequis
- Docker / Docker Compose
- Python 3.12+
- Node.js 20+
- npm
- Accès aux secrets d’environnement métier et tiers

## Étapes d’installation
1. Copier les exemples d’environnement utiles depuis `api-server/.env*.example`.
2. Générer les secrets initiaux avec `bash scripts/generate_secrets.sh`.
3. Renseigner au minimum : base de données, Redis, token interne metrics, secrets JWT, credentials providers.
4. Installer les dépendances backend si exécution hors Docker.
5. Installer les dépendances frontend si exécution hors Docker.

## Vérifications minimales
- `bash scripts/audit_package.sh --check`
- `bash scripts/run_plan_fg_quality.sh` si environnement de test complet disponible
- `bash scripts/preflight_go_v25.sh` pour la validation release

## Règles de livraison
- Ne jamais inclure d’artefacts build/runtime dans l’archive finale.
- Ne pas déclarer “Production Ready” sans exécution du round-trip manuel documenté.
- Archiver les preuves de validation sécurité, B2B, monitoring et déploiement.
