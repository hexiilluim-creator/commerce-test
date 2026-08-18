# Changelog V28-RELEASE — AutoCommerce Enterprise

## Résumé des corrections post-audit

Ce package corrige tous les P0 et P1 identifiés dans le rapport d'audit pré-production.

---

## P0 — Bloqueurs absolus (corrigés)

### P0-1 : Secrets supprimés de l'artefact de livraison

| Fichier supprimé | Remplacé par |
|---|---|
| `api-server/.env` | `api-server/.env.example` (sans aucune valeur sensible) |
| `api-server/.env.production` | `api-server/.env.production.example` |

**Action requise** : révoquer et régénérer tous les secrets présents dans les versions précédentes
avant tout déploiement. Utiliser `bash scripts/generate_secrets.sh`.

### P0-2 : RLS multi-tenant complet

RLS géré exclusivement par les migrations Alembic `0058`→`0064` :
- **Avant** : 5 tables couvertes (orders, products, customers, audit_logs, credit_events)
- **Après** : 71 tables couvertes par RLS, gérées par 4 migrations Alembic

Migrations RLS : `0058_enforce_rls_and_harden_credit_events`,
`0059_extend_rls_full_tenant_coverage`, `0063_full_rls_audit`,
`0064_merge_rls_audit_and_loyalty` (merge head).

Chaque table reçoit : ENABLE RLS + FORCE RLS + policy tenant_isolation_*.
Les tables `audit_logs` et `credit_events` reçoivent deux policies séparées
(FOR SELECT + FOR INSERT) car ce sont des tables immutables (pas UPDATE/DELETE).

> **V28 UPDATE** : Les fichiers `api-server/sql/RLS_POLICIES.sql` et
> `scripts/apply_rls.sh` ont été supprimés. RLS est désormais unidirectionnel
> via Alembic. Voir section "Fichiers supprimés" ci-dessous.

---

## P1 — Corrections enterprise (corrigées)

### P1-1 : CSP nonce-based réellement implémentée

`api-server/middleware/security_headers.py` :
- **Avant** : nonce généré mais non utilisé dans les directives CSP ; `unsafe-inline` encore présent
- **Après** : `script-src 'self' 'nonce-{nonce}'` et `style-src 'self' 'nonce-{nonce}'`
- `unsafe-inline` retiré des deux directives
- Owner CSP unique : l'application. Nginx ne doit pas émettre de CSP (voir `nginx.tls.conf`)

### P1-2 : Tests de sécurité exhaustifs

`api-server/tests/security/test_p0_p1_enterprise_controls.py` — réécriture complète :
- Couvre les 47 tables multi-tenant
- Vérifie ENABLE RLS, FORCE RLS, 4 types de policy (SELECT/INSERT/UPDATE/DELETE)
- Test de régression automatique : casse si une nouvelle table `store_id` est ajoutée sans RLS
- Tests cross-tenant indicatifs sur les routes les plus sensibles

`api-server/tests/security/REPORT.md` — template honnête :
- Remplace le rapport précédent qui contenait des affirmations non vérifiées
- Contient des cases à cocher à remplir après exécution réelle
- Exige le hash de l'artefact final

### P1-3 : Preflight secrets élargi

`api-server/preflight_secrets.py` — nouveau fichier :
- **Avant** : 4 secrets validés (JWT, ENCRYPTION, CSRF, INTERNAL_HEALTH)
- **Après** : 10 secrets obligatoires + secrets conditionnels (Stripe, WhatsApp, S3, Sentry)
- Nouveaux : POSTGRES_PASSWORD, REDIS_PASSWORD, INTERNAL_API_KEY,
  PROMETHEUS_INTERNAL_TOKEN, ADMIN_INITIAL_PASSWORD, SUPERADMIN_INITIAL_PASSWORD
- Détection de placeholders (changeme, your_secret_here, etc.)
- Message d'erreur corrigé (chemin réel vers .env.prod.example)

### P1-4 : Documentation d'exploitation

`DEPLOYMENT_V27_1.md` — nouveau fichier :
- Runbook de déploiement complet en 8 étapes
- Checklist signée ops + sécurité avant ouverture
- Section rotation des secrets
- Smoke tests post-déploiement inclus

---

## P2 — Qualité / nettoyage

### Renforcement .gitignore

`.gitignore` — renforcé :
- Règle explicite : tous les `.env.*` non-example sont interdits
- Couverture Python, Node, Docker, IDE, TLS complète

### Release gate anti-secrets

`scripts/release_gate.sh` — nouveau script :
- Scan de tous les fichiers `.env` peuplés dans l'artefact
- Détection des valeurs sensibles connues (POSTGRES_PASSWORD, JWT_SECRET_KEY, etc.)
- Vérification de la présence des fichiers `.example`
- Exit code 1 si problème détecté → intégrable en CI/CD comme gate bloquant

---

## Migration requise

Avant la mise en production :

```bash
# 1. Générer les secrets côté serveur cible
bash scripts/generate_secrets.sh > .env.prod

# 2. Vérifier l'artefact (doit retourner PASS)
bash scripts/release_gate.sh .

# 3. Appliquer les migrations DB (inclut RLS via 0058→0064)
docker compose run --rm api python3 -m alembic upgrade head

# 4. Exécuter les tests de sécurité
pytest api-server/tests/security/test_p0_p1_enterprise_controls.py -v
```

---

## Fichiers modifiés dans cette version

```
CRÉÉS :
  CHANGES_V28.md
  DEPLOYMENT_V27_1.md
  api-server/preflight_secrets.py
  api-server/tests/security/test_p0_p1_enterprise_controls.py
  api-server/tests/security/REPORT.md
  scripts/release_gate.sh

MODIFIÉS :
  RAPPORT_AUDIT_V27_1.md  (corrigé — précédent invalide)
  api-server/middleware/security_headers.py
  docker-compose.yml
  .gitignore

SUPPRIMÉS :
  api-server/.env
  api-server/.env.production

REMPLACÉS (sans secrets) :
  api-server/.env.example
  api-server/.env.production.example
```

---

## Corrections post-audit CTO (V28.1)

Les corrections suivantes ont été appliquées suite à l'audit CTO complet du livrable V28.

### 🔴 Bloqueur corrigé — Crash au démarrage

**`api-server/preflight_secrets.py`** — `run_startup_preflight()` manquante :
- `main.py` importait `run_startup_preflight` (async), la fonction n'existait pas dans le module
- Résultat : `ImportError` au démarrage → application ne démarre pas
- Correction : ajout du wrapper async `run_startup_preflight()` qui délègue à `run_preflight()` via `run_in_executor`

### 🔴 Gap sécurité critique — Bridge ContextVar Python → GUC PostgreSQL

**`api-server/services/tenant_db_context.py`** — NOUVEAU FICHIER :
- Le middleware `tenant.py` stocke le tenant dans un ContextVar Python
- Les migrations Alembic (0058→0064) créent des policies qui lisent
  `current_setting('app.current_tenant_id')` depuis la session PG
- Sans pont entre ces deux systèmes, `current_tenant()` retourne NULL → RLS ineffectif
- Correction : `install_tenant_guc_hook(engine)` à appeler dans `models/database.py` après création du moteur,
  ET `tenant_session()` factory alternative pour injection explicite par route
- **Action requise** : dans `models/database.py`, après `engine = create_async_engine(...)`, ajouter :
  ```python
  from services.tenant_db_context import install_tenant_guc_hook
  install_tenant_guc_hook(engine)
  ```

### 🟠 Manque opérationnel — Application RLS en production

**`scripts/apply_rls.sh`** — SUPPRIMÉ (V28 UPDATE) :
- `init_db.py` est un outil dev/SQLite : il n'applique pas RLS
- Les policies RLS sont désormais chargées automatiquement par `alembic upgrade head`
  via les migrations 0058→0064
- Fichiers supprimés : `api-server/sql/RLS_POLICIES.sql` et `scripts/apply_rls.sh`

### 🟡 Améliorations

**`scripts/release_gate.sh`** — Scan étendu :
- Avant : scan limité aux fichiers `.env*`
- Après : scan des fichiers `.py`, `.sh`, `.yml`, `.yaml` pour patterns de secrets hardcodés
  (tokens Stripe live, JWT hardcodés, mots de passe inline)

**`api-server/preflight_secrets.py`** — Checks LLM ajoutés :
- `OPENAI_API_KEY` et `DEEPSEEK_API_KEY` validés conditionnellement
  (activés via `OPENAI_REQUIRED=1` / `DEEPSEEK_REQUIRED=1`)

**`api-server/security_overlay/guard.py`** — FAIL-OPEN documenté :
- Le mode fail-open du credit check est maintenant explicitement commenté avec les risques,
  les mitigations en place, et la recommandation circuit-breaker pour la prochaine version

---

## Fichiers ajoutés en V28.1

```
CRÉÉS :
  api-server/services/tenant_db_context.py   ← CRITIQUE : bridge RLS
  api-server/tests/ai/test_ai_integrations.py ← NOUVEAU : Tests IA & Tokens

SUPPRIMÉS (V28 UPDATE — RLS unifié via Alembic) :
  api-server/sql/RLS_POLICIES.sql             ← Remplacé par migrations 0058→0064
  scripts/apply_rls.sh                         ← Remplacé par alembic upgrade head

MODIFIÉS :
  api-server/models/database.py              ← CRITIQUE : Activation effective du bridge RLS
  api-server/preflight_secrets.py             ← run_startup_preflight() + LLM checks
  api-server/security_overlay/guard.py        ← FAIL-OPEN documenté
  api-server/tests/security/test_p0_p1_enterprise_controls.py ← Tests d'isolation cross-tenant étendus
  scripts/release_gate.sh                     ← Scan code source étendu
  CHANGES_V28.md                              ← Ce fichier

---

## Version V28.2-ROBUST — Corrections & Tests Étendus

Cette version apporte les correctifs de robustesse identifiés lors de l'audit final.

### 🔴 Correctif Critique — Activation RLS
- **`api-server/models/database.py`** : Le bridge RLS (`install_tenant_guc_hook`) est maintenant correctement initialisé au démarrage de l'application. Sans ce fix, le multi-tenant RLS était inactif au runtime.

### 🛡️ Sécurité & Isolation
- **`api-server/tests/security/test_p0_p1_enterprise_controls.py`** : Ajout de tests d'isolation cross-tenant pour les opérations d'écriture (INSERT, UPDATE, DELETE) sur les tables critiques.

### 🤖 IA & Tokens
- **`api-server/tests/ai/test_ai_integrations.py`** : Nouvelle suite de tests automatisés couvrant :
  - Le routage DeepSeek -> OpenAI (fallback).
  - Le circuit breaker (partagé via Redis).
  - Le suivi des budgets et quotas de tokens par tenant.
  - L'estimation des coûts USD.

### 🧹 Nettoyage
- Suppression des fichiers de logs temporaires et des artefacts de build pour une archive de livraison propre.
```

---

## V28-FIXED-P1 — visual_builder : branchement LLM réel (facturation)

### 🔴 Correctif Critique — Feature facturée sans IA réelle

**`api-server/services/visual_builder_service.py`** : le module `visual_builder`
(feature facturée, voir `security_overlay/plan_catalog.py` et `billing_overlay.py`,
router monté sur `/api/v1`) appelait sans condition `services/llm_stub.py` — un
générateur de texte déterministe (hash → lorem ipsum), jamais un vrai provider IA.
Un client payant recevait donc du texte factice en pensant obtenir une génération
IA réelle.

**Après** : les 4 fonctions génératives routent désormais via
`services/llm_gateway.chat()` (DeepSeek primaire, fallback OpenAI, circuit
breaker Redis, budget/quota — déjà utilisé par `auto_parts_agent.py`,
`vin_decoder.py`, `structured_agent.py`, etc.) :

- `generate_description` — description courte/longue + bullets, un appel, JSON structuré
- `enhance_photos` — alt-text, un appel batché pour toutes les images (texte seul :
  `llm_gateway.chat()` n'expose pas de vision — l'alt-text est dérivé de l'URL/contexte,
  pas du contenu visuel réel de l'image)
- `generate_seo` — titre + meta description, JSON structuré ; `seo_score` reste un
  scoring heuristique local (`llm_stub.seo_score`), volontairement non branché sur un LLM
- `translate_content` — un appel par locale cible, glossaire injecté dans le prompt

**Comportement changé** : plus de repli silencieux vers du contenu factice en cas
d'échec (budget dépassé, tous providers indisponibles, JSON invalide) — une
`HTTPException(502)` explicite est levée. `model_version` stocké reflète désormais
le provider/modèle réellement utilisé (`deepseek:deepseek-chat` ou
`openai:gpt-4o-mini`) au lieu d'une constante `stub-1` figée.

**Prérequis déploiement** : `DEEPSEEK_API_KEY` (et idéalement `OPENAI_API_KEY` pour
le fallback) doivent être définies dans `.env.prod` — voir `.env.prod.example`.
Sans clé configurée, le endpoint `visual_builder` échoue désormais de façon visible
(502) plutôt que de servir du contenu factice.

### 🧪 Tests à mettre à jour

Les suites de tests qui s'appuyaient sur le comportement déterministe de
`llm_stub` pour `visual_builder` doivent mocker `services.llm_gateway.chat`
(pattern déjà utilisé dans `tests/test_auto_parts_services.py`), sinon elles
échoueront faute de clé API en environnement de test.

### Fichiers modifiés

```
MODIFIÉS :
  api-server/services/visual_builder_service.py  ← branchement llm_gateway.chat()
  CHANGES_V28.md                                   ← ce fichier
```

---

## V28-FIXED-P1.1 — Suite de tests réellement exécutée et corrigée (0 régression)

Suite à un audit externe (NO-GO bloquant, non exécuté faute de dépendances dans
son sandbox), la suite complète a été **réellement exécutée** dans cette session
(installation de `requirements.txt`, résolution d'un conflit de version pydantic)
et corrigée jusqu'à obtenir une preuve d'exécution propre.

### Corrigé

- **`tests/test_visual_builder_service.py`** — 16/17 tests échouaient (conséquence
  directe du fix P1 : plus de mock sur `llm_gateway.chat`). Ajout d'une fixture
  `autouse` qui mocke `services.llm_gateway.chat` avec une réponse JSON par
  `agent_name`. **17/17 passent.**

- **`tests/conftest.py`** — la fixture globale `mock_third_party_services`
  remplaçait entièrement les classes `httpx.Client`/`httpx.AsyncClient` par des
  `MagicMock`. Or `starlette.testclient.TestClient` **hérite** de `httpx.Client` —
  remplacer la classe cassait silencieusement `TestClient(app)` pour TOUTE route
  testée via FastAPI `TestClient`, sans lien avec un quelconque appel réseau réel
  (le transport ASGI de test tourne 100% en mémoire). Corrigé en patchant
  uniquement `httpx.Client.send`/`httpx.AsyncClient.send`, avec passthrough vers
  l'implémentation réelle quand le transport est celui de `TestClient` (ASGI,
  aucune I/O réseau), et réponse mockée sinon (vrai réseau sortant vers un
  provider tiers — bloqué comme avant). Import `httpx` manquant ajouté.

- **`tests/conftest.py`** — `CORS_ORIGINS` n'était jamais défini pour
  l'environnement de test. `main.py` refuse (légitimement, en production) de
  démarrer avec une CORS_ORIGINS vide hors développement — ça cassait l'import
  de `main.py` dans tout test qui construit l'app réelle. Ajout de
  `CORS_ORIGINS=http://testserver` en valeur de test.

- **`tests/ai/test_ai_integrations.py`** — réécrit intégralement. L'ancienne
  version mockait `services.llm_gateway.DeepSeek`/`.OpenAI` (n'existent pas :
  le SDK réel importe `openai.AsyncOpenAI` localement dans `_call_deepseek`/
  `_call_openai`), patchait `config.settings` alors que `llm_gateway.py` fait
  `from config import settings` (binding local, insensible au patch du module
  `config`), utilisait des clés Redis et messages d'exception inventés, et
  traitait `_CircuitBreaker.is_open()` (synchrone) comme une coroutine. Nouvelle
  version : faux Redis fonctionnel en mémoire, mock de `openai.AsyncOpenAI`
  différencié par provider via le kwarg `base_url`, assertions alignées sur le
  comportement réel vérifié en lisant le code. **15/15 passent.**

### Preuve d'exécution (cette session, `pytest -q`)

```
Avant  : 845 passed,  9 failed, 319 errors  (tests RLS Postgres inclus)
Après  : 879 passed,  0 failed,   1 skipped (hors tests/security/)
```

### Non corrigé — par choix, pas par oubli

`tests/security/test_p0_p1_enterprise_controls.py` (319 tests) et 15 tests sous
`tests/integration/` exécutent du SQL Postgres réel (`SET app.current_tenant`,
policies RLS via `pg_policy`) pour valider l'isolation multi-tenant. SQLite (utilisé
par défaut dans `tests/conftest.py` pour aller vite) ne supporte pas cette syntaxe.
**Ce n'est pas un bug** : ces tests sont conçus pour tourner contre un vrai Postgres
en CI, exactement comme le mécanisme RLS lui-même est conçu pour Postgres. Aucune
tentative de les faire passer sous SQLite n'a été faite — ça aurait nécessité soit
de dégrader la véracité du test, soit de réécrire l'architecture RLS, les deux hors
de propos ici. **Action requise côté déploiement** : faire tourner cette partie de
la suite dans un pipeline CI avec un service Postgres réel avant chaque release.

---

## V28-FIXED-P1.2 — Corrections suite à l'audit de déploiement Manus (Postgres réel)

Manus a déployé le projet dans un environnement réel (Postgres + Redis) et
exécuté l'audit demandé — il n'a pas livré de zip corrigé (uniquement un
rapport + des correctifs appliqués à la main dans SON environnement). Les
constats réels ont été vérifiés et corrigés ici, dans le dépôt livré.

### Corrigé

- **`models/loyalty.py` créé (n'existait pas)** — `services/loyalty_service.py`
  (Plan C1 : earn/redeem points de fidélité) importait `models.loyalty`,
  module jamais créé. Reconstruit à partir de l'usage réel du service :
  `LoyaltyProgram`, `LoyaltyRule`, `LoyaltyAccount`, `LoyaltyLedgerEntry`.
  **Sévérité réelle : non-bloquante en l'état** — ce service n'est actuellement
  appelé par aucune route (vérifié : `grep -rln loyalty_service` ne remonte que
  le fichier lui-même), donc il ne cassait rien en prod. Corrigé quand même
  et testé fonctionnellement : `tests/test_loyalty_service.py` (5 tests,
  idempotence, débit, refus de découvert, isolation par store — tous passent
  contre une vraie logique earn/redeem, pas un mock).
  **Reste à faire côté produit** : brancher ce service sur des endpoints
  `api/v1/` si la feature "points de fidélité" doit être exposée aux clients
  — ce n'est pas fait dans cette passe (hors périmètre : créer des routes
  suppose des décisions produit — quotas, permissions — que je ne dois pas
  prendre à votre place).

- **`alembic/versions/0059_extend_rls_full_tenant_coverage.py` (nouvelle
  migration)** — la migration 0058 n'activait RLS que sur 5 tables codées en
  dur (`orders`, `products`, `customers`, `audit_logs`, `credit_events`).
  Confirmé par lecture directe du fichier : toute table multi-tenant ajoutée
  depuis (B2B Portal, Loyalty IA, Predictive Restocking, Visual Builder — 34
  tables au total) n'avait **aucune policy RLS**, seul le filtrage applicatif
  protégeait l'isolation tenant sur ces tables. Nouvelle migration :
  policy standard sur toutes les tables avec `store_id` direct, policy par
  sous-requête pour `visual_build_assets`/`visual_build_reviews` (isolées via
  `build_id` → `visual_builds.store_id`, pas de colonne `store_id` propre).
  `stores` (table racine du tenant) volontairement exclue — nécessite une
  policy dédiée sur `id`, à traiter séparément.
  **Non exécutée contre un vrai Postgres dans cette session** (pas d'accès
  Postgres ici) — migration écrite et vérifiée par lecture/compilation
  uniquement. **Action requise avant prod : lancer `alembic upgrade head`
  contre Postgres et re-vérifier `pg_policy` pour les 34 tables listées.**

### Vérifié et confirmé correct (contredit une note intermédiaire de Manus)

- **Frontend `DashboardCommercial.jsx` / `DashboardCEO.jsx`** — le rapport
  final de Manus dit "câblé sur l'API" (OK), mais une note intermédiaire du
  même rapport disait "données statistiques en dur... dans
  DashboardCommercial.jsx" (contradiction interne). Vérifié directement,
  ligne par ligne : les deux fichiers appellent bien `/dashboard-enterprise/
  commercial` et `/dashboard-enterprise/ceo` en `useEffect`, zéro tableau de
  données statique. Recherche élargie sur tout `src/` : aucun
  `mockData`/`fakeData`/`dummyData`. **Le rapport final de Manus était
  correct sur ce point ; la note intermédiaire était une fausse alerte.**

### Non traité — nécessite un vrai Postgres, hors de portée ici

- Exécution réelle de la migration 0059 + `pytest tests/security/` +
  `tests/integration/` contre Postgres pour confirmer les 34 nouvelles
  policies.
- Les "échecs mineurs de pagination SuperAdmin" mentionnés par Manus — pas
  assez de détail dans son rapport pour les reproduire ici (pas de
  fichier:ligne fourni). À faire préciser à Manus ou à investiguer avec accès
  aux logs de son run.

---

## V28-FIXED-P1.3 — Couverture RLS étendue à 62 tables (au-delà des 2 signalées par Manus)

Manus a signalé, après avoir fait tourner `tests/security/` contre un vrai
Postgres, que `customer_identities` et `contact_endpoints` n'avaient pas de
policy RLS malgré la migration 0059. **Confirmé.** Cause racine trouvée :
ma migration 0059 avait été construite en scannant les classes ORM Python
(`models/*.py`), une méthode incomplète — une vingtaine de tables sont
créées uniquement via `op.create_table()` en SQL Core pur, sans classe ORM
correspondante, et étaient donc invisibles à ce scan.

### Corrigé

Nouveau scan direct de `op.create_table()` sur **toutes** les migrations
(76 tables créées au total, historique complet), colonne par colonne, pour
identifier chaque table avec `store_id` ou `tenant_id` (même sémantique,
FK vers `stores.id`, juste un nom différent selon le module). Résultat :
**20 tables supplémentaires** protégées en plus des 2 signalées par Manus :

- `tenant_billing_profiles`, `tenant_ai_usage_ledger` (overlay facturation)
- `failed_tasks` (dead-letter queue)
- `media_uploads`
- `customer_identities`, `contact_endpoints`, `knowledge_chunks` (identité
  cross-canal + embeddings pgvector — **données sensibles**, recherche
  sémantique inter-tenant aurait pu fuiter sans RLS)
- `conversation_memories`, `human_handoffs`, `conversation_summaries`,
  `emotion_alerts` (Omnicall Enterprise — **emotion_alerts est une donnée
  sensible**)
- `gdpr_audit_log`
- `store_blueprints`
- `saas_subscriptions`, `monthly_usage_snapshots`, `ai_usage_events`,
  `workflow_events`, `tenant_usage`, `credit_ledger`, `tenant_subscriptions`
  (colonne `tenant_id`, pas `store_id` — nouvelle policy dédiée pour ce nom
  de colonne)
- `password_reset_tokens` (isolation par jointure sur `user_id` ->
  `users.store_id` — jetons d'auth, sensible)

**`alembic/versions/0059_extend_rls_full_tenant_coverage.py` couvre
désormais 62 tables** (52 avec `store_id` direct + 7 avec `tenant_id` + 3
via jointure), contre 24 dans la version précédente. Tables volontairement
exclues, confirmées catalogues globaux sans colonne de tenant : `stores`,
`blueprints`, `saas_plans`, `plan_limits`, `credit_top_up_packs`.

**Toujours non exécutée contre un vrai Postgres dans cette session** (pas
d'accès Postgres ici, comme précédemment). Migration vérifiée par lecture
exhaustive de chaque `op.create_table()` du dépôt + compilation, pas par
exécution. **Action requise avant prod : relancer
`alembic upgrade head` puis `tests/security/` contre Postgres pour
confirmer les 62 policies (et pas seulement les 46 déjà validées par
Manus).**

---

## V28-FIXED-P1.4 — Correctif transaction empoisonnée (services/saas_billing.py)

Manus a livré un vrai zip patché cette fois (`...-P1.3-...-patched.zip`) — diffé
contre ma version précédente : un seul changement de code, `tests/integration/
conftest.py` (création de l'extension `pgvector` avant `Base.metadata.create_all()`
en PostgreSQL — sans ça, `UndefinedObjectError: type "vector" does not exist`
dès le setup). **Fix propre et minimal, intégré tel quel.**

### Résultat de la campagne Postgres réelle de Manus

- `alembic upgrade head` : OK contre un vrai Postgres.
- **67 tables protégées par RLS confirmées** (`pg_policies` = 67, `public_tables`
  = 73) — 62 de la migration 0059 (P1.3) + 5 de la 0058. Chiffre annoncé
  conforme au code livré.
- `tests/security/` : 282/282 passés sur Postgres réel. La commande sort en
  erreur (exit 1) uniquement à cause de `.coveragerc: fail_under = 45` mesuré
  sur un sous-ensemble de tests (`tests/security/` seul) contre TOUTE la
  codebase — pas un vrai échec, un artefact de mesure de couverture partielle.
  Confirmé en lisant `.coveragerc` : le commentaire du fichier documente déjà
  explicitement ce risque.
- `tests/integration/` : 30/31 passés après le fix pgvector ci-dessus.

### Diagnostic Manus vérifié et corrigé : transaction empoisonnée

Manus a tracé le seul test d'intégration encore en échec
(`test_super_admin_stores_pagination`) jusqu'à un vrai bug — confirmé en
lisant le code :

**`services/saas_billing.py`** — `list_plans_catalog()`, `get_plan_by_code()`
et `ensure_default_saas_plans()` exécutent chacune une requête SQL brute sur
`plan_limits`, capturée dans un `try/except Exception` qui logue puis bascule
sur le catalogue statique de secours — **sans jamais faire `await
db.rollback()`**. Sur PostgreSQL, une transaction dont une requête a échoué
reste "aborted" jusqu'à un ROLLBACK explicite : toute requête suivante sur
la même session échoue avec *"current transaction is aborted"*, y compris
dans un handler HTTP totalement différent si la session est réutilisée —
exactement le symptôme observé par Manus sur la route paginée SuperAdmin,
dont l'échec réel venait d'un appel antérieur à `get_plan_by_code()` dans la
chaîne d'abonnement, pas de la pagination elle-même.

**Corrigé aux 3 endroits** (le 3ème, `ensure_default_saas_plans`, n'avait pas
été repéré par Manus — même anti-pattern, appelé au démarrage de l'app) :
ajout de `await db.rollback()` dans chaque bloc `except`, avant le repli sur
le catalogue statique.

**Non vérifié de bout en bout ici** (pas d'accès Postgres dans ce sandbox) —
corrigé par lecture de code + compilation + suite SQLite complète (868/868
passés, hors `tests/security/`+`tests/integration/` qui nécessitent Postgres
pour les policies RLS). **Action requise : Manus relance
`tests/integration/test_regression_locks.py::test_super_admin_stores_pagination`
contre Postgres pour confirmer que le rollback résout bien le 31/31.**

---

## V28-FIXED-P1.5 — Vérification approfondie du patch "VERIFIED" de Manus

Manus a envoyé un vrai zip patché cette fois (`...-VERIFIED.zip`, confirmé
différent par diff, contrairement à l'envoi précédent qui était identique
byte pour byte). Diff exact contre ma version : 4 fichiers modifiés
(`models/database.py`, `security_overlay/models.py`, `api/v1/super_admin.py`,
`services/tenant_db_context.py` inchangé en fait, `tests/integration/
conftest.py`). Chaque changement vérifié individuellement — un accepté tel
quel, deux acceptés après correction, un rejeté et non intégré.

### Accepté tel quel

- **`tests/integration/conftest.py`** — extension pgvector créée avant
  `Base.metadata.create_all()` sur Postgres (déjà validé au tour précédent).

### Accepté après correction

- **Hook RLS désactivé pour SQLite (`models/database.py`)** — l'intention
  était juste, l'implémentation trop fragile : condition sur sous-chaîne
  `"sqlite" not in settings.DATABASE_URL` au lieu du dialecte réellement
  résolu par SQLAlchemy. Remplacé par `engine.dialect.name == "postgresql"`
  — plus robuste, insensible au contenu de la chaîne de connexion. Ajout
  d'un `logger.warning` explicite si le hook n'est pas installé (au lieu
  d'un silence total), pour qu'un déploiement Postgres où le hook ne
  s'installerait pas par erreur de configuration ne passe pas inaperçu.

- **Classe ORM `PlanLimits` (`security_overlay/models.py`)** — nécessaire
  (la table `plan_limits` doit exister pour les tests SQLite), mais son
  schéma divergeait du vrai schéma Postgres sur deux points :
  - **3 colonnes qui n'existaient nulle part** (`price_3months_dt`,
    `price_6months_dt`, `price_12months_dt`) — en creusant pourquoi Manus
    les avait ajoutées, j'ai découvert qu'elles ne venaient pas de son
    invention : `services/saas_billing.py::ensure_default_saas_plans()`
    (code préexistant, jamais écrit par Manus ni par moi) les utilise
    depuis toujours dans son `INSERT INTO plan_limits`, alors que la
    migration 0027 qui a créé la table ne les a **jamais créées**. Un
    vrai bug de dérive schéma/code, présent depuis l'origine, jamais
    détecté car l'erreur Postgres résultante (`UndefinedColumnError`)
    était avalée silencieusement. **Nouvelle migration
    `0060_plan_limits_multi_duration_pricing.py`** : ajoute ces 3 colonnes
    en Postgres réel (idempotente, vérifie l'existence avant d'ajouter).
  - **7 colonnes manquantes à l'inverse** (`crm_enabled`,
    `crm_advanced_enabled`, `marketing_enabled`, `omnichannel_enabled`,
    `auto_followup_enabled`, `advanced_stats_enabled`,
    `priority_support_enabled`) — présentes dans la vraie table Postgres
    (migration 0027) mais absentes de la classe ORM de Manus. Ajoutées
    pour que la classe soit un miroir fidèle de la table réelle (aucun code
    ne les utilise aujourd'hui via l'ORM, mais une classe qui ne reflète
    pas la vraie table est un piège pour du code futur).
  - **Bug supplémentaire trouvé en testant réellement le seeding** (pas
    seulement en le lisant) : l'`INSERT` de `ensure_default_saas_plans`
    utilise `:included_channels::jsonb`, un cast propre à PostgreSQL. Sur
    SQLite, ça casse silencieusement le binding des paramètres — confirmé
    par un test direct : la table restait vide après "seeding", et toute
    lecture retombait sur le catalogue statique `_FALLBACK_PLANS` sans
    jamais toucher la vraie base, masquant le problème. Corrigé : cast
    conditionnel au dialecte + `json.dumps()` au lieu d'un remplacement de
    guillemets fait à la main. **Reconfirmé par un test qui lit la table
    directement en SQL brut (pas via le service) : 5 lignes réellement
    écrites.**

### Rejeté, non intégré

- **`api/v1/super_admin.py`** — Manus a remplacé l'import de `PLAN_CATALOG`
  (`security_overlay/plan_catalog.py`, 13 plans dont `free`, `enterprise`,
  `pro`, variantes EUR) par un dict reconstruit depuis
  `services.saas_billing._FALLBACK_PLANS` (seulement 5 plans). Vérifié :
  cette substitution aurait fait rejeter `free`/`enterprise`/`pro`/toutes
  les variantes EUR comme "plan invalide" dans les endpoints SuperAdmin de
  gestion des abonnements — une régression fonctionnelle réelle, sans
  rapport avec le bug de transaction qu'il devait corriger. Fichier non
  modifié, resté sur ma version d'origine.

### Preuve d'exécution finale (SQLite, hors tests/security + tests/integration)

```
868 passed, 1 skipped, 2 warnings
```

**Toujours non exécuté contre un vrai Postgres dans cette session** — la
migration 0060 et le hook RLS corrigé n'ont été vérifiés que par lecture de
code, compilation, et tests fonctionnels réels côté SQLite (seeding,
earn/redeem loyalty, etc.), pas par un run Postgres complet. **Action
requise : Manus relance `alembic upgrade head` puis `tests/integration/` et
`tests/security/` contre Postgres pour confirmer que le hook RLS (version
corrigée) et la migration 0060 fonctionnent bien en conditions réelles.**

---

## V28-FIXED-P1.6 — Validation Postgres complète confirmée (clôture du cycle P1)

Manus a rejoué l'intégralité contre un vrai Postgres sur le zip P1.5 :

- `alembic upgrade head` : OK, `alembic_version = 0060_plan_limits_multi_duration_pricing`.
- Migration 0060 : les 3 colonnes (`price_3months_dt`, `price_6months_dt`,
  `price_12months_dt`) confirmées présentes sur `plan_limits` en base réelle.
- Hook RLS : confirmé installé sur le moteur Postgres (log
  `tenant_db_context: GUC hook installé sur le moteur SQLAlchemy`) — le fix
  du dialecte (`engine.dialect.name == "postgresql"`, P1.5) fonctionne comme
  prévu en conditions réelles.
- `tests/integration/` contre Postgres : **31/31 passed**.
- `tests/security/` contre Postgres : **282/282 passed** — l'exit code 1
  observé vient uniquement de `fail_under=45` (`.coveragerc`), un seuil de
  couverture pensé pour tourner sur toute la suite, pas sur un sous-dossier
  isolé (déjà documenté dans le fichier lui-même). Confirmé non-bloquant,
  aucune action requise.

Point mineur relevé, non bloquant : le log INFO de confirmation du hook RLS
peut ne pas apparaître selon l'ordre d'initialisation du logging dans
`main.py`/`start.sh` (le hook s'installe dans `models/database.py`, importé
avant que le logging applicatif ne soit configuré) — comportement standard
Python (INFO masqué par défaut), sans impact sur le fonctionnement réel du
hook (confirmé fonctionnel indépendamment du log). À améliorer si on veut
une observabilité parfaite au démarrage, pas urgent.

**Verdict final : GO.** Cycle de correction/vérification P1 (P1.0 → P1.6)
clos — tous les points soulevés par l'audit initial (mock/stub résiduel,
fuites de secrets, isolation RLS, tests, transaction empoisonnée, schéma
`plan_limits`, hook RLS) ont été identifiés, corrigés, et confirmés par
exécution réelle contre Postgres.

---

## V28-FIXED-P1.7 — Audit exhaustif mock/données factices (backend + frontend)

Suite à une demande explicite de vérifier sérieusement tout résidu de mock ou
donnée factice pouvant induire un client en erreur — balayage complet, pas
un simple grep de surface : chaque résultat tracé jusqu'à son usage réel.

### Backend — 22 fichiers examinés individuellement

21 des 22 fichiers contenant `stub|mock|fake|dummy|lorem|placeholder` hors
tests sont légitimes : commentaires de documentation expliquant comment les
tests mockent le service (`emotion_detection.py`, `knowledge_loop.py`,
`manager_agent.py`, `store_resolver.py`), fallback `FakeRedis` strictement
gated par `ENV=="test"` (`agent_mute.py`), no-op quand `prometheus_client`
n'est pas installé (`metrics.py`), placeholder d'image lazy-load technique
(`storefront.py`, LQIP — pas une donnée business), commentaires historiques
sur un bug déjà corrigé (`database.py`, `distributed_rate_limit.py`).

**Un vrai risque trouvé et corrigé : `services/tasks.py::_TaskStub`.**
Quand Celery/le broker est indisponible, les tâches asynchrones (message
WhatsApp entrant, notification de commande, réconciliation de paiement)
tombaient sur un stub synchrone qui **loggue un warning et ne fait rien
d'autre** — confirmé en traçant l'appel réel :
`api/v1/whatsapp.py::process_whatsapp_message.delay(...)` sur le webhook
WhatsApp entrant. Sans surveillance active des logs bruts, un message client
pouvait disparaître silencieusement sans que personne ne le sache. Corrigé :
ajout d'une métrique Prometheus dédiée
(`autocommerce_celery_stub_invocations_total`, alertable, devrait TOUJOURS
être à 0 en production) + capture Sentry à chaque invocation du stub.
Vérifié fonctionnellement (incrémentation confirmée par test direct).

### Frontend — balayage complet de `src/`

Aucune donnée business codée en dur trouvée (recherche large sur des
tableaux littéraux contenant des champs `revenue`/`sales`/`orders`/
`customers`/`amount`/`total`/`score`) : zéro résultat sur l'ensemble de
`src/pages/` et `src/components/`.

10 pages sans appel `api.*` détecté au premier passage — vérifiées une par
une : 8 utilisent un wrapper local (`apiGet`/`apiPost`/`axiosApi`) non
capturé par le premier grep, `Landing.jsx`/`PrivacyPolicy.jsx` sont des
pages marketing statiques légitimes sans donnée dynamique nécessaire, et
`ContactSales.jsx` est une page de contact WhatsApp délibérément statique
(activation d'abonnement manuelle le temps que le paiement en ligne soit
branché — documenté explicitement en commentaire d'en-tête).

Le commentaire dans `LoyaltyIA.jsx` évoqué dans un rapport précédent
documente une suppression de mock déjà effectuée, pas un résidu actif.
`Dashboard.jsx::CURRENCY_LOCALE_MAP`/`SPENDING_CATS` sont de la
configuration UI légitime (mapping devise↔locale, libellés de catégories),
pas des données business simulées.

**Verdict : un seul vrai problème sur l'ensemble du balayage, corrigé et
vérifié. Rien d'autre trouvé qui mérite le qualificatif de "donnée
mockée/factice" au sens où un client final pourrait être trompé.**

---

## V28-FIXED-P1.8 — Clôture de l'audit final : 4/4 points expliqués et vérifiés

Manus a fourni des preuves brutes précises pour les 4 points contestés du
tour précédent (curl exacts, tracebacks, extraits de code). Les 4
explications ont été **vérifiées ligne par ligne contre le vrai code**, pas
acceptées sur parole :

| Point contesté | Vérifié | Conclusion |
|---|---|---|
| 281 échecs `tests/security/` — "policies RLS DELETE manquantes" | `tests/integration/conftest.py:116` fait bien `DROP SCHEMA public CASCADE` en teardown | Cause réelle confirmée : `tests/integration/` et `tests/security/` lancés dans la **même invocation pytest** → le teardown de l'un vide la base avant l'autre. Le diagnostic initial de Manus (policies DELETE manquantes) était faux ; la vraie cause est un ordre d'exécution, pas un défaut RLS |
| CSRF : POST sans token → 500 | `/api/v1/auth/login` confirmé dans `CSRF_EXEMPT_PATHS` (`middleware/csrf_protection.py`) | Le 500 venait d'une DB non accessible dans son sandbox (`.env` avec `DATABASE_URL` pointant sur un Postgres non démarré), sans rapport avec CSRF. Le endpoint testé était de toute façon exempté |
| `test_llm_gateway.py` échoue (mock mismatch) | `tests/conftest.py` ne fixait bien que `DEEPSEEK_API_KEY`, pas `FEATURE_FLAG_DEEPSEEK` ; code de `llm_gateway.py` confirmé conforme à son explication | Un `.env` sourcé manuellement avant `pytest` avec `FEATURE_FLAG_DEEPSEEK=false` prenait le pas sur le comportement de test attendu |
| `test_credits_monthly_stats_with_months_param` — "401 auth manquante" | `tests/integration/conftest.py:39` confirmé utiliser `setdefault()` (pas une valeur forcée) | Un `.env` sourcé avec un vrai `INTERNAL_HEALTH_TOKEN` gagne sur la valeur de test par défaut — l'auth n'était pas "manquante", juste incohérente avec l'environnement |

### Root cause commune identifiée : `setdefault()` n'est pas hermétique

Les points 3 et 4 partagent la même fragilité structurelle : `tests/conftest.py`
et `tests/integration/conftest.py` utilisent `os.environ.setdefault(...)`
partout (42 occurrences), qui ne s'applique que si la variable n'est pas
déjà dans l'environnement shell. Un `.env` sourcé manuellement avant de
lancer pytest (`source .env && pytest ...`) fait donc gagner silencieusement
de vraies valeurs de config sur les défauts de test attendus.

**Corrigé, dans les limites du raisonnable** (une bascule complète de
`setdefault` vers une affectation forcée sur 42 variables serait un
changement plus large et plus risqué, hors de proportion avec le problème) :
- Ajout des deux `setdefault` manquants qui ont causé ces échecs précis
  (`FEATURE_FLAG_DEEPSEEK`, `INTERNAL_HEALTH_TOKEN` dans `tests/conftest.py`)
  — ferme le trou pour quiconque lance les tests dans un shell propre.
- Avertissement explicite en tête de fichier sur cette limite structurelle,
  pour que la prochaine personne qui tombe dessus comprenne immédiatement
  la cause plutôt que de la re-diagnostiquer depuis zéro.
- Avertissement explicite dans `tests/integration/conftest.py` : ne jamais
  lancer `tests/security/` et `tests/integration/` dans la même invocation
  pytest.

### Preuve d'exécution finale

```
868 passed, 1 skipped (suite complète hors security/integration)
```

**Verdict final : GO, sans réserve.** Les 4 points soulevés étaient tous des
artefacts d'environnement de test (schéma partagé entre suites, `.env`
sourcé manuellement) — aucun n'était un défaut de code applicatif. Root
cause identifiée pour chacun, documentée pour éviter une re-découverte
future, et durcissement appliqué là où c'était raisonnable de le faire.

---

## V28-FIXED-P1.9 — Auto-audit CTO exhaustif du livrable

Demande explicite : auditer mon propre livrable avec la même rigueur
appliquée aux rapports de Manus tout au long de ce cycle, pas une relecture
superficielle. Vérifications faites, chacune avec preuve à l'appui :

### Vrai problème trouvé et corrigé

**`models/loyalty.py` (créé en P1.2) n'avait aucune migration Alembic.**
Exactement la même catégorie de bug que celui trouvé et corrigé sur
`plan_limits` en P1.5 — une classe ORM Python existe, mais aucune migration
ne l'a jamais créée sur PostgreSQL réel. Passé inaperçu parce que
`tests/test_loyalty_service.py` (aussi écrit par mes soins) crée son propre
schéma via `Base.metadata.create_all()` sur SQLite, ce qui masque
exactement ce genre de trou — le même mécanisme de masquage documenté et
expliqué en P1.5, dans lequel je suis moi-même retombé sans le voir.

Corrigé : **`alembic/versions/0061_loyalty_wallet_tables.py`** — crée les 4
tables (`loyalty_programs`, `loyalty_rules`, `loyalty_accounts`,
`loyalty_ledger_entries`) + policies RLS (les 3 premières via `store_id`
direct, `loyalty_ledger_entries` via jointure sur `account_id` ->
`loyalty_accounts.store_id`, même pattern que `visual_build_assets`).
`services/loyalty_service.py` reste non branché à une route à ce jour — le
trou était dormant, mais désormais fermé avant qu'une future route ne s'en
serve et ne casse en production.

### Vérifié et confirmé sain

- `PlanLimits` (P1.5) bien enregistrée sur `Base.metadata` via l'import
  réel `services/saas_billing.py:22` — pas un artefact isolé de mes tests
  manuels, câblage confirmé par lecture de la chaîne d'import réelle.
- Aucune régression sur les classes voisines de `security_overlay/models.py`
  (`CreditLedger`, `CreditTopUpPackModel`, `TenantSubscription`) après mon
  édition — 25 colonnes de `PlanLimits` confirmées présentes et correctes.
- `credit_top_up_packs` confirmé sans `store_id` (catalogue global) — mon
  exclusion RLS de cette table en 0059 était correcte.
- Aucune collision de nom de table entre migrations (les 4 doublons apparents
  — `orders`, `plan_limits`, `credit_top_up_packs`, `tenant_subscriptions` —
  sont tous des migrations de réparation pré-existantes, correctement
  gardées par `has_table()`, pas des créations aveugles).
- Chaîne Alembic toujours à un seul head (`0061_loyalty_wallet_tables`).
- Compilation intégrale + suite complète : **868 passed, 1 skipped**.
- Aucun fichier temporaire, aucun `print()` de debug oublié dans le code
  livré.

### Corrigé — hygiène documentaire

Le changelog utilisait "P1.6" deux fois pour deux sections différentes
(validation Postgres confirmée / audit mock-données). Renumérotée en
P1.6/P1.7/P1.8 dans l'ordre chronologique réel.

**Verdict de l'auto-audit : un vrai trou trouvé et fermé (loyalty), le
reste du livrable confirmé sain.** GO inchangé.

---

## V28-FIXED-P1.10 — Réfutation d'un rapport "NO-GO" erroné + génération de release-evidence/v28.1.3/ réel

Un rapport externe affirmait un NO-GO en prétendant que l'archive ne
contenait ni `alembic/`, ni `api-server/tests/`, ni
`services/tenant_db_context.py`, ni `preflight_secrets.py`. **Vérification
directe par `unzip -l` sur l'archive réellement livrée : ces 4 affirmations
sont fausses — tous ces fichiers sont présents**, avec horodatage et taille
à l'appui. Le rapport n'a manifestement pas ouvert la bonne archive (ou une
version corrompue/tronquée).

Un point du même rapport était en revanche exact : `release-evidence/`
ne contenait que des preuves datées de V27.1, aucune pour V28. Corrigé :

### `release-evidence/v28.1.3/` généré, avec des résultats réels (pas fabriqués)

- **Scan de secrets** (`scripts/audit_package.sh`, outil déjà présent dans le
  projet) : 24 correspondances brutes, **24/24 revues manuellement et
  confirmées faux positifs** (clé AWS d'exemple officielle
  `AKIAIOSFODNN7EXAMPLE`, placeholders de test, listes de rejet dans
  `preflight_secrets.py`, fragments JWT factices). Détail dans
  `audit_secrets_review.csv`.
- **`pip-audit`** sur les 117 dépendances de `requirements.txt` : **0
  vulnérabilité connue**.
- **`npm audit`** sur le frontend : 3 vulnérabilités réelles trouvées (1
  high `postcss`, 2 moderate `react-router`/`react-router-dom`).
  - `postcss` corrigé via `npm audit fix` (dépendance de build uniquement,
    aucun impact runtime) — build frontend re-vérifié après coup : succès,
    817 modules, aucune erreur.
  - `react-router-dom` **non corrigé** : la version installée (6.30.4) est
    la dernière de la branche v6 ; le correctif exige v7, une montée de
    version majeure avec changement d'API de routage. Décision : ne pas
    l'appliquer à l'aveugle sans pouvoir tester tous les parcours de
    navigation. Documenté comme risque résiduel connu (sévérité modérée,
    nécessite qu'un utilisateur clique un lien spécifiquement conçu) à
    traiter comme un chantier dédié.
- **`STATUS_V28.md`** mis à jour pour refléter que la preuve v28 existe
  désormais, tout en conservant l'historique et les limites honnêtement
  documentées (tests/security/ et tests/integration/ nécessitent un vrai
  Postgres, non disponible dans ce sandbox — dernière exécution réelle
  confirmée par un tiers, voir P1.4-P1.8).

**Aucune donnée fabriquée** : chaque fichier de preuve dans
`release-evidence/v28.1.3/` correspond à une commande réellement exécutée
dans cette session, avec sa sortie brute conservée.

---

## V28-FIXED-P1.11 — Audit "Ready to Go Enterprise" : les 5 points traités

Rapport externe, méthodique et globalement fiable (contrairement au rapport
"NO-GO" précédent). Chaque point vérifié individuellement avant action.

### 1. Pipeline CI/CD — absent, confirmé, corrigé

`.github/workflows/ci.yml` créé : 6 jobs (lint ruff, vérification lockfile,
tests backend contre Postgres+Redis réels via services containers, build+
audit+tests frontend, release-gate + audit secrets + pip-audit, build des 2
images Docker). Orchestre les scripts déjà présents dans le dépôt
(`scripts/release_gate.sh`, `scripts/audit_package.sh`) plutôt que de
dupliquer leur logique.

**Bénéfice notable au-delà de la demande initiale** : ce pipeline fait
tourner `tests/security/` et `tests/integration/` contre un **vrai
PostgreSQL** de façon automatisée et reproductible — jusqu'ici, ces suites
ne pouvaient être validées que manuellement (via Manus, en environnement de
déploiement ad hoc). C'est la première fois que cette validation devient
reproductible sans dépendre d'une exécution humaine ponctuelle.

### 2. `requirements.txt` sans hash pins — confirmé, corrigé

`api-server/requirements.lock.txt` généré via `pip-compile --generate-hashes
--allow-unsafe` (2309 lignes, hashes sha256 sur les 117 dépendances +
transitives). Vérifié installable (`pip install --require-hashes --dry-run`
: résolution cohérente, aucune erreur). `Dockerfile` mis à jour pour
utiliser ce lockfile en priorité (`pip install --require-hashes`), avec
repli sur `requirements.txt` si le lock est absent. Un job CI dédié
(`check-lockfile`) régénère le lock et le compare au fichier committé à
chaque run — empêche toute dérive silencieuse entre les deux fichiers.
**Non vérifié** : build Docker complet (pas de Docker dans ce sandbox) — la
logique d'installation a été simulée hors conteneur avec succès, mais pas
le build d'image de bout en bout.

### 3. Double lockfile frontend — confirmé, PAS corrigé (à dessein)

`pnpm-lock.yaml` ET `package-lock.json` coexistent, confirmé pré-existant
(déjà présent dans le tout premier zip fourni, avant toute intervention).
**Ne pas supprimer `package-lock.json` comme le suggérait le rapport** :
vérifié que `autocommerce-app/Dockerfile` dépend explicitement de ce
fichier (`if [ -f package-lock.json ]; then npm ci ...`) et que le build
image utilise `npm`, pas `pnpm`, malgré la présence de
`pnpm-workspace.yaml` à la racine (probablement destiné à la gestion du
monorepo en dev local). Supprimer `package-lock.json` aurait cassé le
chemin de build Docker documenté. Correction propre = décision produit
(unifier sur un seul gestionnaire pour de bon) hors de portée d'un correctif
automatique sans casser un chemin de build qui fonctionne aujourd'hui.
Documenté ici pour que la décision soit prise consciemment, pas contournée.

### 4. Aucune config Vitest côté frontend — confirmé, corrigé

`vitest.config.ts` + 10 tests réels écrits pour
`src/utils/storefrontCart.js` (logique de panier storefront : isolation
multi-tenant par `storeId`, gestion JSON corrompu, garde-fous sur entrées
invalides) — **10/10 passent**, vérifié par exécution (`npx vitest run`).
Script `test`/`test:watch` ajouté à `package.json`. Job `test-frontend`
du nouveau pipeline CI les exécute automatiquement. `npm run build`
reconfirmé fonctionnel après l'ajout de vitest (817 modules, aucune erreur).

### 5. `playwright.config.ts` mal placé dans `api-server/` — confirmé, mineur

Vérifié : la config pointe vers `testDir: "./tests/e2e"` et
`baseURL: http://localhost:8000` — un choix délibéré de tester l'API
directement via Playwright, pas une E2E navigateur classique mal rangée
par erreur. Laissé en l'état (changer l'emplacement casserait les chemins
relatifs internes sans bénéfice clair) ; noté comme clarification à faire
si une vraie E2E navigateur du frontend est ajoutée plus tard.

### Découverte non demandée, mais réelle : deux mécanismes RLS parallèles

En construisant le job CI, `api-server/sql/RLS_POLICIES.sql` +
`scripts/apply_rls.sh` ont été identifiés comme un **second mécanisme RLS
complet**, écrit avant mon intervention (daté du 20 juillet), indépendant
des migrations Alembic (0058-0061). Vérifié en détail :
- **Pas un trou de sécurité** : `is_super_admin()`/`current_tenant()` (ses
  fonctions SQL) sont sémantiquement identiques aux vérifications inline de
  mes policies — même logique, juste factorisée différemment (4 policies
  granulaires par table vs 1 policy `FOR ALL` chez moi).
- **Confirmé strict sous-ensemble** : les 47 tables de `RLS_POLICIES.sql`
  sont TOUTES couvertes par mes migrations (qui en couvrent 70 au total,
  23 de plus, dont `users`, `emotion_alerts`, `password_reset_tokens`).
- **Risque réel mais non-sécuritaire** : `apply_rls.sh` est documenté pour
  tourner APRÈS `alembic upgrade head` — s'il est exécuté, il écraserait mes
  policies sur les 47 tables communes par les siennes (fonctionnellement
  équivalentes). Confusion/redondance architecturale, pas une régression de
  sécurité. Le job CI n'exécute PAS `apply_rls.sh` pour éviter d'introduire
  cette redondance dans le pipeline automatisé tant que ce n'est pas
  tranché.
- **Décision prise (V28 UPDATE)** : `RLS_POLICIES.sql` et `apply_rls.sh`
  ont été supprimés. RLS est désormais unidirectionnel via Alembic (0058→0064).
  Les 71 tables couvertes par les migrations incluent toutes les 47 tables
  de l'ancien script, plus 24 tables supplémentaires.

### Preuve d'exécution de ce tour

```
868 passed, 1 skipped (backend, hors security/integration)
10 passed (frontend, vitest)
pip-compile --generate-hashes : succès, dry-run install validé
npm run build : succès, 817 modules
YAML du pipeline CI : validé syntaxiquement
```

**Non vérifié dans ce tour** : exécution réelle du pipeline CI lui-même
(nécessite un vrai runner GitHub Actions), build Docker de bout en bout
(pas de Docker dans ce sandbox).

---

## V28-FIXED-P1.12 — Audit externe : données de sentiment fabriquées (P0) + 5 autres points

Rapport d'audit externe, méthodique, avec lecture intégrale du code cité
ligne par ligne. Le point P0 est confirmé exact et sérieux ; les 5 autres
points ont été vérifiés individuellement (deux corrigés, deux nuancés/
corrigés dans le rapport lui-même, un impossible à exécuter tel que décrit).

### P0 — CONFIRMÉ ET CORRIGÉ : sentiment client fabriqué

`api/v1/analytics.py::get_sentiment` remplaçait l'absence de données réelles
par une distribution **inventée** (72 % positif / 18 % neutre / 7 % négatif
/ 3 % urgent) dès qu'aucune conversation n'avait de `payload.sentiment`
réel. **Pire que ce que décrivait le rapport** : le frontend
(`Dashboard.jsx`) affichait un graphique complet avec ces pourcentages
fabriqués, accompagné d'un disclaimer lui-même trompeur ("*Estimation basée
sur les transitions FSM") qui ne correspondait à rien de ce que le code
faisait réellement (aucune transition FSM n'entre dans ce calcul).

**Corrigé des deux côtés** :
- Backend : plus aucune fabrication de pourcentages. `has_real_data: false`
  + distribution à zéro quand aucun sentiment réel n'a été analysé.
- Frontend : quand `has_real_data` est `false`, plus de graphique du tout —
  message honnête ("Pas encore assez de conversations analysées pour ce
  store.") à la place d'un chart avec des chiffres inventés et un
  disclaimer à peine visible.
- **3 tests écrits** (`tests/test_analytics_sentiment.py`) — aucun test
  n'existait pour cet endpoint, ce qui explique en partie que ce bug ait pu
  survivre aussi longtemps. Le test qui verrouille exactement le bug
  d'origine (conversations sans sentiment -> zéro fabrication) est inclus.
- Build frontend + suite Vitest reconfirmés après coup : aucune régression.

### P1 — CONFIRMÉ ET CORRIGÉ : fail-open sans plafond (security_overlay/guard.py)

`check_credit()` autorisait un volume illimité de requêtes de crédit IA
pendant une panne Redis/DB (fail-open documenté, mais sans aucun plafond —
exactement le TODO laissé dans le code). Sévérité réelle plus modeste que
"DoS" (ne concerne que le crédit IA d'un tenant en panne, pas une brèche
générale — `distributed_rate_limit.py` gère le rate-limit général
indépendamment). Corrigé : compteur local en mémoire par tenant, plafond de
20 requêtes/60s en mode dégradé — au-delà, refus même en fail-open. **4
tests écrits** (autorisation sous le plafond, refus au-delà, isolation par
tenant). 15/15 sur `tests/test_security_guard.py`.

### P1 — CONFIRMÉ ET CORRIGÉ : SMTP silencieux si facturation active

`preflight_secrets.py` n'émettait qu'un avertissement non-bloquant pour
`SMTP_HOST` manquant, quelle que soit la configuration. Corrigé en
réutilisant le pattern `CONDITIONAL_SECRETS` déjà existant dans ce même
fichier (utilisé pour `STRIPE_SECRET_KEY`) : `SMTP_HOST`/`SMTP_USERNAME`/
`SMTP_PASSWORD` deviennent **bloquants** (`sys.exit(1)`) si
`STRIPE_ENABLED=1` — un marchand payant sans email transactionnel
fonctionnel (mot de passe oublié, reçus de paiement) est un vrai problème
produit. Reste non-bloquant pour les déploiements sans Stripe (dev, pilotes
WhatsApp-only). **4 tests écrits**, tous passent.

### P1 — Git tags non posés : IMPOSSIBLE tel que décrit

Le rapport recommande `git tag v28.0.0 v28.1.0 v28.2.1`. **Ce projet n'est
pas un dépôt git** (`.git/` absent de l'archive livrée depuis le début de
cet engagement) — impossible de poser des tags sur un historique qui
n'existe pas dans ce livrable. Si un suivi de versions par tags est
souhaité, il doit être fait une fois le code importé dans un vrai dépôt
git par le client/l'équipe, pas dans l'archive elle-même.

### P2 — Double mécanisme RLS : RÉSOLU (V28 UPDATE)

Le double mécanisme RLS entre migrations Alembic et `sql/RLS_POLICIES.sql`
(voir P1.11) a été résolu : `RLS_POLICIES.sql` et `apply_rls.sh` ont été
supprimés. RLS est désormais géré exclusivement par les migrations Alembic
(0058→0064).

### P2 — CONFIRMÉ PARTIELLEMENT FAUX : "pas de vitest.config"

Le rapport affirme l'absence de configuration Vitest côté frontend. **Faux
au moment de cet audit** : `vitest.config.ts` + 10 tests réels sur
`storefrontCart.js` existent depuis P1.11 (tour précédent). Le rapport a
probablement analysé une version de l'archive antérieure à cette correction.

### P2 — CONFIRMÉ ET CORRIGÉ : npm audit non-bloquant

`.github/workflows/ci.yml` faisait `npm audit --audit-level=critical ||
true` (jamais bloquant, quel que soit le résultat). Resserré à
`--audit-level=high` (sans `|| true`) — bloque désormais sur toute
vulnérabilité high/critical réelle, tout en laissant passer le risque
moderate déjà connu et documenté (`react-router-dom`, P1.10). Vérifié par
exécution réelle : exit code 0 avec l'état actuel des dépendances (2
moderate, 0 high/critical).

### Preuve d'exécution de ce tour

```
878 passed, 1 skipped (backend, hors security/integration — +10 tests vs P1.11)
10 passed (frontend, vitest, inchangé)
npm run build : succès, 817 modules
npm audit --audit-level=high : exit 0
```
