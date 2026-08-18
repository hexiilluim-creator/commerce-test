---
severity: critical
owner: Security Team
MTTD: 5m
MTTR: 10m
---

# Runbook: Kill Switch Tenant

## Symptômes

- Demande de désactivation immédiate d'un tenant pour raison de sécurité/abus.
- Alerte `TenantAbuseDetected` (à créer).

## Cause probable

- Activité suspecte détectée sur un tenant (fraude, spam, attaque).
- Demande légale de désactivation.

## Étapes diagnostic

1. **Confirmer la demande:** Vérifier la source de la demande (équipe sécurité, légal).
2. **Identifier le tenant:** Obtenir le `tenant_id` ou `store_id`.
3. **Vérifier l'activité:** Consulter les logs et les métriques du tenant.

## Étapes mitigation

1. **Activer le kill switch:** Utiliser l'endpoint `/api/v1/_internal/tenant/kill-switch` (protégé par `X-Internal-Token`).
2. **Vérifier la désactivation:** Tenter d'accéder au tenant via l'API ou le frontend.
3. **Auditer les logs:** S'assurer que les accès au tenant sont bloqués et loggés.

## Post-mortem template

- **Date et heure de l'incident:**
- **Durée:**
- **Services affectés:**
- **Cause racine:**
- **Actions correctives:**
- **Actions préventives:**

