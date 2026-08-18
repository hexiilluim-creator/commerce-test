# Rapport de correction — AutoCommerce Enterprise V27.2-P2

Date: 2026-07-20

## Objet
Correction des échecs signalés dans le rapport de validation V27.2-P2, avec livraison d'une archive projet prête à l'emploi.

## Correctifs appliqués

### 1) `api-server/services/credit_ledger.py`
Correction de compatibilité d'appel sur les fonctions de lecture du ledger :

- `get_ledger_history(...)`
- `get_usage_summary(...)`

#### Cause racine
Les tests appelaient ces fonctions avec un argument nommé `store_id=...`, alors que l'implémentation n'acceptait que des arguments positionnels via `*args`.

#### Correctif
- ajout d'une normalisation centralisée des paramètres
- prise en charge des appels suivants :
  - `get_ledger_history(store_id=1, limit=10)`
  - `get_ledger_history(1, limit=10)`
  - `get_ledger_history(db, 1, limit=10)`
  - `get_usage_summary(store_id=10)`
  - `get_usage_summary(10)`
  - `get_usage_summary(db, 10)`

#### Impact
- suppression du `TypeError: unexpected keyword argument 'store_id'`
- compatibilité ascendante maintenue pour les appels legacy

## Vérifications effectuées

### Validation syntaxique
- `python3 -m py_compile api-server/services/credit_ledger.py`
- résultat : OK

### Validation tests ciblés du rapport
Commande exécutée :

```bash
pytest -q --no-cov tests/test_credit_ledger.py tests/test_ai_guardrails.py
```

Résultat :
- **32 tests passés / 32**
- **0 échec**

Détail pertinent :
- `tests/test_credit_ledger.py` : OK
- `tests/test_ai_guardrails.py` : OK

## Fichiers modifiés
- `api-server/services/credit_ledger.py`
- `RAPPORT_CORRECTION_TESTS_V27_2_P2.md`

## Packaging
L'archive finale a été régénérée en excluant les artefacts locaux de validation :
- `.venv/`
- `__pycache__/`
- `.pytest_cache/`
- `htmlcov/`
- `api-server/reports/`

## Statut final
- Correctif appliqué
- Tests ciblés du rapport validés
- Archive prête à être livrée
