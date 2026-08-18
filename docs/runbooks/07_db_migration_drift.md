---
severity: critical
owner: DevOps Team
MTTD: 10m
MTTR: 30m
---

# Runbook: DB Migration Drift

## Symptômes

- Erreurs `AlembicMigrationError` au démarrage de `api-server`.
- Incohérences de schéma entre la base de données et le code.
- Déploiement échoue en raison de problèmes de migration.

## Cause probable

- Une migration n'a pas été appliquée correctement.
- Des modifications manuelles ont été faites sur la base de données.
- Conflit entre les migrations locales et celles du dépôt.

## Étapes diagnostic

1. **Vérifier les logs de démarrage:** `kubectl logs -f <api-server-pod>` pour les erreurs Alembic.
2. **Vérifier le statut des migrations:** `alembic history` et `alembic current`.
3. **Générer un diff:** `alembic revision --autogenerate -m "Check for drift"` pour voir les différences.

## Étapes mitigation

1. **Appliquer les migrations manquantes:** `alembic upgrade head` (en environnement de dev/staging d'abord).
2. **Revertir le dernier déploiement:** Si le problème est lié à un déploiement récent.
3. **Corriger les modifications manuelles:** Si des modifications manuelles sont la cause, les annuler ou créer une migration pour les intégrer.

## Post-mortem template

- **Date et heure de l'incident:**
- **Durée:**
- **Services affectés:**
- **Cause racine:**
- **Actions correctives:**
- **Actions préventives:**

