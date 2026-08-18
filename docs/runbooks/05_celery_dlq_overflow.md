---
severity: warning
owner: SRE Team
MTTD: 30m
MTTR: 60m
---

# Runbook: Celery DLQ Overflow

## Symptômes

- Alerte Grafana: `DLQBacklog`
- Logs: Messages `task_failed_max_retries` dans les logs de `celery-worker`.
- Tâches asynchrones critiques non traitées.

## Cause probable

- Une tâche Celery échoue de manière répétée et finit en DLQ.
- Problème de dépendance externe (DB, API tierce) rendant les tâches impossibles à traiter.
- Erreur de code dans une tâche Celery.

## Étapes diagnostic

1. **Vérifier l'alerte Grafana:** Confirmer la taille de la DLQ.
2. **Consulter les logs de Celery:** `kubectl logs -f <celery-worker-pod> | grep task_failed_max_retries`
3. **Inspecter les tâches en DLQ:** Utiliser l'interface de monitoring Celery (Flower) ou `celery -A services.celery_app inspect active_queues`.
4. **Identifier la tâche problématique:** Déterminer quelle tâche est en cause.

## Étapes mitigation

1. **Corriger la cause racine:** Si c'est un problème de code, déployer un correctif.
2. **Purger la DLQ (avec précaution):** `celery -A services.celery_app purge -Q <dlq_queue_name>` (uniquement si les tâches sont irrécupérables).
3. **Redémarrer les workers Celery:** `kubectl rollout restart deployment celery-worker`

## Post-mortem template

- **Date et heure de l'incident:**
- **Durée:**
- **Services affectés:**
- **Cause racine:**
- **Actions correctives:**
- **Actions préventives:**

