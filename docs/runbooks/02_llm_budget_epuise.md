---
severity: warning
owner: AI Team
MTTD: 60m
MTTR: 120m
---

# Runbook: Budget LLM Épuisé

## Symptômes

- Alerte Grafana: `AIMonthlyBudgetApproachingLimit` ou `AIMonthlyBudgetExceeded`
- Logs: Erreurs `LLM_BudgetExceeded` dans les logs de `api-server`.

## Cause probable

- Utilisation excessive des modèles LLM.
- Configuration de budget trop basse.
- Fuite de requêtes LLM.

## Étapes diagnostic

1. **Vérifier l'alerte Grafana:** Confirmer le niveau d'alerte et le seuil atteint.
2. **Consulter les logs:** `kubectl logs -f <api-server-pod> | grep LLM_BudgetExceeded`
3. **Vérifier l'utilisation actuelle:** Consulter le panneau "LLM provider usage ($)" dans Grafana.
4. **Identifier les agents/stores consommateurs:** Analyser les logs pour les `store_id` ou `agent_name` les plus actifs.

## Étapes mitigation

1. **Augmenter temporairement le budget:** Mettre à jour `AI_BUDGET_HARD_LIMIT_USD` dans les `settings` (nécessite un redéploiement).
2. **Désactiver les agents IA non critiques:** Mettre à jour les `FEATURE_FLAG_AI_AGENT_X` dans les `settings`.
3. **Optimiser les prompts:** Revoir les prompts des agents IA pour réduire la consommation de tokens.

## Post-mortem template

- **Date et heure de l'incident:**
- **Durée:**
- **Services affectés:**
- **Cause racine:**
- **Actions correctives:**
- **Actions préventives:**

