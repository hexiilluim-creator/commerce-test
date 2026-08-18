# Rapport d'audit V28 — Production hardening AutoCommerce Enterprise

> **Statut** : Ce document remplace le RAPPORT_AUDIT_V27_1.md qui contenait des affirmations incorrectes
> (il déclarait la suppression des secrets alors que des fichiers .env peuplés étaient toujours présents).

## Base de travail
- Package analysé : **AutoCommerce Enterprise V27.1**
- Package produit : **AutoCommerce Enterprise V28-RELEASE**
- Rapport d'audit tiers utilisé : `Pasted-Rapport-preproduction-P0-P1-P2.txt`

## Corrections réalisées (V28)

### P0 — Bloqueurs absolus corrigés

#### P0-1 : Secrets dans l'archive
| Fichier | Action |
|---|---|
| `api-server/.env` | **Supprimé** → remplacé par `api-server/.env.example` (sans aucune valeur sensible) |
| `api-server/.env.production` | **Supprimé** → remplacé par `api-server/.env.production.example` |
| `.env.prod.example` | Conservé (était déjà propre) |

**Rotation des secrets** : tous les secrets qui étaient présents dans les fichiers supprimés
doivent être révoqués et régénérés côté infrastructure avant tout déploiement.
Utiliser `bash scripts/generate_secrets.sh` pour générer de nouveaux secrets.

#### P0-2 : Isolation multi-tenant incomplète
| Fichier | Action |
|---|---|
| `api-server/sql/RLS_POLICIES.sql` | **Créé** — couvre 47 tables multi-tenant (vs 5 avant) |

Tables couvertes (sections) :
- **Section 1** : tables de base (database.py) — 28 tables
- **Section 2** : B2B portal (b2b_portal.py) — 5 tables
- **Section 3** : IA fidélité (loyalty_ia.py) — 5 tables
- **Section 4** : réassort prédictif (predictive_restocking.py) — 4 tables
- **Section 5** : visual builder (visual_builder.py) — 4 tables dont 2 par jointure

Chaque table reçoit : `ENABLE RLS`, `FORCE RLS`, policy SELECT+INSERT+UPDATE+DELETE.
Les tables `audit_logs` et `credit_events` sont immutables (pas de UPDATE/DELETE).

### P1 — Corrections enterprise

#### P1-1 : CSP nonce-based réellement implémentée
| Fichier | Changement |
|---|---|
| `api-server/middleware/security_headers.py` | Le nonce est maintenant injecté dans `script-src` et `style-src`. `unsafe-inline` retiré des deux directives. |

Stratégie CSP unifiée : **l'application est le seul owner de la CSP**.
Nginx ne doit PAS émettre de header `Content-Security-Policy` (voir consignes `nginx.tls.conf`).

#### P1-2 : Tests de sécurité exhaustifs
| Fichier | Changement |
|---|---|
| `api-server/tests/security/test_p0_p1_enterprise_controls.py` | Réécriture complète — couvre les 47 tables, ENABLE+FORCE+4 types de policy, test de régression automatique |
| `api-server/tests/security/REPORT.md` | Remplacé par template honnête à remplir après exécution réelle |

#### P1-3 : Preflight secrets élargi
| Fichier | Changement |
|---|---|
| `api-server/preflight_secrets.py` | Créé / remplacé — valide 10 secrets obligatoires + secrets conditionnels (Stripe, WhatsApp, S3, Sentry) |

#### P1-4 : Documentation d'exploitation
| Fichier | Changement |
|---|---|
| `DEPLOYMENT_V27_1.md` | Créé — runbook de prod complet avec checklist signée avant go-live |

### P2 — Qualité / nettoyage

| Fichier | Changement |
|---|---|
| `.gitignore` | Renforcé — refus strict de tous les `.env.*` non-example |
| `scripts/release_gate.sh` | Créé — scan anti-secrets bloquant avant release |

## Ce qui reste à faire côté déploiement réel

1. **Rotation complète** des secrets exposés dans V27.1 (même s'ils semblent changés, la prudence impose la révocation)
2. **Migration DB** : exécuter `api-server/sql/RLS_POLICIES.sql` sur la base cible
3. **Unification CSP Nginx** : retirer le header `Content-Security-Policy` de `nginx.tls.conf`
4. **Integration des tests** dans le pipeline CI/CD avec `pytest api-server/tests/security/`
5. **Exécution du release gate** : `bash scripts/release_gate.sh` doit passer à zéro erreur avant toute distribution
6. **Remplissage du rapport** : `api-server/tests/security/REPORT.md` avec hash artefact réel

## Points qui restent forcément côté infrastructure cible

- Vrais domaines / DNS / certificats TLS
- Vraies clés LLM / Meta / Stripe / S3 (ne jamais les mettre dans l'artefact)
- Backup/restore réellement branché sur l'infra cible
- Supervision et alerting raccordés à l'environnement final
- Rotation tracée des secrets post-déploiement

## Fichiers modifiés / créés dans cette version

```
CRÉÉS :
  api-server/sql/RLS_POLICIES.sql                     (690 lignes, 47 tables)
  api-server/preflight_secrets.py                      (élargi)
  api-server/tests/security/test_p0_p1_enterprise_controls.py  (réécriture)
  api-server/tests/security/REPORT.md                  (template honnête)
  DEPLOYMENT_V27_1.md                                  (runbook complet)
  scripts/release_gate.sh                              (scan anti-secrets)

MODIFIÉS :
  api-server/middleware/security_headers.py            (CSP nonce réel)
  .gitignore                                           (renforcé)
  RAPPORT_AUDIT_V27_1.md                              (ce fichier — corrigé)

SUPPRIMÉS :
  api-server/.env                                      (contenait des secrets réels)
  api-server/.env.production                           (contenait des secrets réels)

AJOUTÉS (.example sans secrets) :
  api-server/.env.example
  api-server/.env.production.example
```
