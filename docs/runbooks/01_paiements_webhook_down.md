---
severity: critical
owner: SRE Team
MTTD: 15m
MTTR: 30m
---

# Runbook: Paiements Webhook Down

## Symptômes

- Alerte Grafana: `PaymentWebhookStuck`
- Logs: Erreurs `webhook_processing_failed` dans les logs de `api-server`.

## Cause probable

- Problème de connectivité avec le fournisseur de paiement.
- Erreur dans le traitement du webhook côté `api-server`.
- Défaillance du service de queue (Celery).

## Étapes diagnostic

1. **Vérifier l'alerte Grafana:** Confirmer l'heure de début et la durée de l'incident.
2. **Consulter les logs:** `kubectl logs -f <api-server-pod> | grep webhook_processing_failed`
3. **Vérifier l'état de Celery:** `celery -A services.celery_app inspect ping`
4. **Vérifier la connectivité externe:** `curl -I https://api.stripe.com` (ou autre PSP)

## Étapes mitigation

1. **Redémarrer le service `api-server`:** `kubectl rollout restart deployment api-server`
2. **Redémarrer Celery:** `kubectl rollout restart deployment celery-worker`
3. **Vérifier le statut du PSP:** Consulter la page de statut du fournisseur de paiement.

## Post-mortem template

- **Date et heure de l'incident:**
- **Durée:**
- **Services affectés:**
- **Cause racine:**
- **Actions correctives:**
- **Actions préventives:**

