---
severity: critical
owner: SRE Team
MTTD: 5m
MTTR: 15m
---

# Runbook: Redis Down

## Symptômes

- Alerte Grafana: `RedisDown`
- Erreurs `RedisConnectionError` dans les logs de `api-server` et `celery-worker`.
- Défaillance des fonctionnalités dépendant de Redis (sessions, cache, rate limiting, circuit breakers).

## Cause probable

- Le service Redis est arrêté ou inaccessible.
- Problème réseau entre les applications et Redis.
- Surcharge de Redis.

## Étapes diagnostic

1. **Vérifier l'alerte Grafana:** Confirmer l'état de l'alerte.
2. **Vérifier le statut du pod Redis:** `kubectl get pods -l app=redis`
3. **Consulter les logs de Redis:** `kubectl logs -f <redis-pod>`
4. **Tester la connectivité:** `redis-cli -h <redis-host> ping` depuis un pod `api-server`.

## Étapes mitigation

1. **Redémarrer le pod Redis:** `kubectl rollout restart deployment redis`
2. **Vérifier la configuration réseau:** S'assurer que les règles de pare-feu n'ont pas changé.
3. **Augmenter les ressources de Redis:** Si surcharge, augmenter CPU/mémoire du pod Redis.

## Post-mortem template

- **Date et heure de l'incident:**
- **Durée:**
- **Services affectés:**
- **Cause racine:**
- **Actions correctives:**
- **Actions préventives:**

