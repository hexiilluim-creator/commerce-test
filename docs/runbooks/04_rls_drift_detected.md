---
severity: critical
owner: Security Team
MTTD: 30m
MTTR: 60m
---

# Runbook: RLS Drift Detected

## Symptômes

- Alerte Grafana: `RLSDriftDetected` (à créer)
- Logs: `RLS_POLICY_VIOLATION` dans les logs de `api-server`.
- Tests de sécurité RLS échouent en CI/CD.

## Cause probable

- Une migration de base de données a supprimé ou modifié une politique RLS.
- Un déploiement a écrasé les politiques RLS.
- Erreur de configuration de la base de données.

## Étapes diagnostic

1. **Vérifier l'alerte Grafana:** Confirmer l'alerte.
2. **Consulter les logs:** `kubectl logs -f <api-server-pod> | grep RLS_POLICY_VIOLATION`
3. **Vérifier les politiques RLS actives:** `SELECT tablename, policyname, cmd FROM pg_policies WHERE policyname LIKE 'tenant_isolation_%' ORDER BY tablename;`

## Étapes mitigation

1. **Réappliquer les politiques RLS:** Exécuter `alembic upgrade head` après avoir vérifié les migrations.
2. **Revertir le dernier déploiement:** Si un déploiement récent est la cause.
3. **Corriger la migration:** Si une migration est en cause, créer une nouvelle migration corrective.

## Post-mortem template

- **Date et heure de l'incident:**
- **Durée:**
- **Services affectés:**
- **Cause racine:**
- **Actions correctives:**
- **Actions préventives:**

