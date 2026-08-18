# Rapport de sécurité — Tests enterprise AutoCommerce V28

> **AVERTISSEMENT** : ce rapport est un template à remplir après exécution réelle sur l'artefact final.
> Un rapport signé manuellement sans preuve reproductible n'est pas un rapport de sécurité valide.

## Métadonnées

| Champ | Valeur |
|---|---|
| Version package | V28-RELEASE |
| Hash artefact (SHA256) | `<remplir après packaging : sha256sum AutoCommerce-Enterprise-V28-RELEASE.zip>` |
| Date exécution | `<date réelle>` |
| Environnement de test | `<dev / staging / prod>` |
| Exécuté par | `<nom>` |

## 1. Scan secrets dans l'artefact

```
bash scripts/release_gate.sh <chemin-archive>
```

| Résultat attendu | Statut |
|---|---|
| Aucun .env peuplé dans l'archive | ☐ PASS / ☐ FAIL |
| Aucune valeur sensible non vide détectée | ☐ PASS / ☐ FAIL |

## 2. Couverture RLS

```
pytest api-server/tests/security/test_p0_p1_enterprise_controls.py -v
```

| Contrôle | Statut |
|---|---|
| ENABLE ROW LEVEL SECURITY — toutes les tables multi-tenant | ☐ PASS / ☐ FAIL |
| FORCE ROW LEVEL SECURITY — toutes les tables | ☐ PASS / ☐ FAIL |
| Policy SELECT (USING) sur toutes les tables | ☐ PASS / ☐ FAIL |
| Policy INSERT (WITH CHECK) sur toutes les tables | ☐ PASS / ☐ FAIL |
| Policy UPDATE sur toutes les tables mutables | ☐ PASS / ☐ FAIL |
| Policy DELETE sur toutes les tables mutables | ☐ PASS / ☐ FAIL |
| Régression : aucune table store_id sans RLS | ☐ PASS / ☐ FAIL |

Tables couvertes : 71 tables multi-tenant protégées par RLS via migrations Alembic (0058→0064).

## 3. Headers de sécurité

```
curl -I https://<domaine>/api/health
```

| Header | Valeur attendue | Statut |
|---|---|---|
| Content-Security-Policy | `script-src 'self' 'nonce-...'` (sans unsafe-inline) | ☐ PASS / ☐ FAIL |
| X-Frame-Options | `DENY` | ☐ PASS / ☐ FAIL |
| Strict-Transport-Security | `max-age=63072000; includeSubDomains; preload` | ☐ PASS / ☐ FAIL |
| Un seul header CSP (pas de doublon Nginx) | ☐ PASS / ☐ FAIL |

## 4. Preflight secrets

```
ENV=production python3 api-server/preflight_secrets.py
```

| Contrôle | Statut |
|---|---|
| Refus si JWT_SECRET_KEY manquant | ☐ PASS / ☐ FAIL |
| Refus si POSTGRES_PASSWORD manquant | ☐ PASS / ☐ FAIL |
| Refus si REDIS_PASSWORD manquant | ☐ PASS / ☐ FAIL |
| Refus si ADMIN_INITIAL_PASSWORD manquant | ☐ PASS / ☐ FAIL |

## 5. Isolation cross-tenant (manuelle)

Pour chaque route critique :
- `POST /api/v1/orders` avec token tenant B → ne doit PAS créer dans tenant A
- `GET /api/v1/orders` avec token tenant B → ne doit PAS retourner les orders de tenant A

| Route | Résultat attendu | Statut |
|---|---|---|
| GET /api/v1/orders | Isolation OK | ☐ PASS / ☐ FAIL |
| GET /api/v1/customers | Isolation OK | ☐ PASS / ☐ FAIL |
| GET /api/v1/conversations | Isolation OK | ☐ PASS / ☐ FAIL |
| POST /api/v1/payment-links | Isolation OK | ☐ PASS / ☐ FAIL |

## Verdict

- [ ] Tous les contrôles P0 passent → package éligible à la mise en production
- [ ] Tous les contrôles P1 passent → package éligible à l'ouverture enterprise

**Ce rapport doit être attaché à l'artefact final avec son hash.**
