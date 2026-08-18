# MERGE_NOTES.md — Version combinée AutoCommerce Enterprise

Générée par recoupement direct des fichiers de trois livrables : P11
(`AutoCommerce-Enterprise-V28-P11-applique-corrige.zip`, VERSION 28.2.1),
V28_2 (`AutoCommerce-Enterprise-V28_2.zip`, VERSION 28.2.4) et V28_2_4-P1
(`AutoCommerce-Enterprise-V28_2_4-P1.zip`, VERSION 28.2.4). Aucune
exécution réelle des tests n'a été possible dans cet environnement (pas
d'accès réseau pour installer les dépendances npm/pip) — cette base est
donc un merge **vérifié statiquement fichier par fichier**, pas rejoué en
CI. À faire tourner en local avant tout déploiement.

## Base retenue : P11 (VERSION 28.2.1)

P11 a été choisie comme socle car c'est, de loin, le paquet le mieux testé
des trois :
- Seuil de couverture backend `fail_under = 80` (vs 45 dans V28_2 et
  V28_2_4-P1)
- 11 fichiers `tests/security/` et 14 `tests/integration/` (vs 2 et 7 dans
  les deux autres)
- Seul paquet avec un `release-evidence/v28.1.3/` complet et daté (logs
  pip_audit, npm_audit, scan de secrets)

**Correction à mon analyse précédente** : j'avais signalé le pont RLS
(`tenant_db_context.py`, `install_tenant_guc_hook`) comme un correctif
manquant dans P11 et présent uniquement dans V28_2_4-P1. Vérification
faite fichier par fichier : **P11 l'a déjà**, identique octet pour octet à
la version dans V28_2_4-P1. Il n'y avait donc pas de régression de
sécurité à corriger sur ce point — je me trompais dans le tour précédent.

## Ce qui a été ajouté depuis V28_2 (2 fichiers + 1 composant)

- `autocommerce-app/src/utils/cartOrderMessage.js` + son test
- `autocommerce-app/src/components/OptimizedCartV2.jsx` (version qui
  importe et utilise réellement `cartOrderMessage.js`)

C'est le **seul** module parmi les 14 "utils extraits" de V28_2 qui est
réellement câblé dans un composant de l'application. Vérifié par
recherche d'import réelle (`from '../utils/xxx'`), pas par la présence du
fichier seule.

## Ce qui a été délibérément laissé de côté

**Les 13 autres fichiers `utils/*.js` de V28_2/V28_2_4-P1** (authValidation,
contactSalesUtils, dashboardMetrics, landingPricing, loyaltyIA,
ordersUtils, paymentLinksUtils, promotionsUtils, roiCalculator,
settingsUtils, socialBroadcastUtils, storefrontBadge, superAdminPricing) —
**ne sont importés nulle part dans l'application**, malgré leurs
commentaires internes affirmant être de la "logique extraite" des pages
correspondantes. Ce sont des tests de code mort/parallèle : ils augmentent
un chiffre de couverture sans tester le comportement réel de l'app. Les
inclure aurait gonflé artificiellement la crédibilité du paquet — exactement
le type de chose à éviter. Si ce travail doit être valorisé, il faut
d'abord câbler chaque module dans le composant qu'il prétend remplacer,
puis vérifier par les tests existants que rien ne casse.

**7 fichiers backend qui diffèrent entre P11 et V28_2_4-P1** (`main.py`,
`config.py`, `services/llm_gateway.py`, `services/agent_orchestrator.py`,
`services/email_service.py`, `services/metrics.py`,
`middleware/security_headers.py`) — **non fusionnés, verdict tranché par
relecture statique du diff complet** (pas d'exécution — impossible dans le
sandbox qui a produit ce paquet, voir plus haut) :

| Fichier | Verdict |
|---|---|
| `main.py` / `config.py` / `services/llm_gateway.py` | P11 garde `guard_provider()` — bloque le démarrage si `LLM_PROVIDER=stub` ou clé API manquante en prod/staging. La version P1 a retiré ce garde-fou. |
| `services/agent_orchestrator.py` | Le commentaire de P1 ("simplifié depuis `if auto_state != auto_idle or True`") ne correspond pas au code réel de P11, qui n'a jamais eu ce bug. P1 a supprimé le routage FSM par état et la branche `business_type == HYBRID` que P11 possède. |
| `services/email_service.py` | P11 passe par `EmailQueue`/`EmailSender` (retry + dead-letter-queue). P1 envoie en direct via `smtplib`, sans file ni retry. |
| `services/metrics.py` | P1 a supprimé le compteur `llm_provider_used_total` (perte d'observabilité mineure). |
| `middleware/security_headers.py` | Quasi neutre — P11 rend HSTS configurable via un flag, P1 l'active en dur. Même comportement par défaut. |

**Conclusion : sur les 5 comparaisons, P11 est égal ou supérieur à chaque
fois.** Confirmé par `diff -q` : les 7 fichiers dans ce paquet sont
**identiques byte-à-byte à leur version P11** — aucune régression de P1
n'a été introduite dans ce merge. Reste à faire, non réalisable dans ce
sandbox (pas de Docker/réseau) : rejouer `tests/` de P11 contre ces 7
fichiers pour confirmer par exécution ce que la lecture statique indique
déjà.

## Ajout depuis V28.2.8-AUDITED (2026-08-05)

12 tests de composants réels + contexte + helpers, copiés depuis
`AutoCommerce-Enterprise-V28_2_8-AUDITED.zip` :
- `src/tests/components/*.test.jsx` (Auth, Dashboard, Orders, PaymentLinks,
  Products, Promotions, Settings, SuperAdmin, AccessControl, Conversations,
  NetworkError) — 11 fichiers
- `src/tests/context/StoreContext.test.jsx`
- `src/tests/helpers/renderWithProviders.jsx`, `mockStore.jsx`
- `src/tests/setup.ts`, branché dans `vitest.config.ts` (`setupFiles`)
- `package.json` : ajout de `@testing-library/react`,
  `@testing-library/user-event`, `@vitest/coverage-v8` (absents de la base
  P11, requis par ces tests)

Contrairement aux modules `utils/*.js` de V28_2/P1 (orphelins, jamais
importés), **ces tests importent réellement les composants** — vérifié par
`grep` sur chaque import. C'est un ajout de valeur, pas du chiffre gonflé.

**⚠️ Non vérifié — à faire avant de considérer ces tests comme acquis** :
ces tests ont été écrits contre la version V28.2.8 des composants, pas
contre celle de P11. Diff effectué entre les deux bases : 7 des 10
composants ciblés **diffèrent** entre P11 et V28.2.8 (Auth 25 lignes,
Dashboard 64, Orders 13, PaymentLinks 73, Promotions 41, Settings 5,
SuperAdmin 49 — Conversations, Products et StoreContext sont identiques).
Impossible de garantir sans exécution que ces tests passent contre les
composants P11 tels quels — `npm install && npm run test` doit être lancé
avant toute confiance dans ces 12 fichiers. Si des tests échouent, c'est
probablement parce que le composant P11 n'a pas le comportement que le
test attend de la version V28.2.8 (ex. prop renommée, texte affiché
différent) — pas nécessairement un bug réel.

## Prochaines étapes recommandées

1. `npm install` puis `npm run test:coverage` dans `autocommerce-app/`
   pour mesurer la couverture réelle après l'ajout de `cartOrderMessage`,
   et fixer `vitest.config.ts` avec le chiffre mesuré (pas un chiffre
   inventé).
2. `pytest` complet côté `api-server/` contre un vrai Postgres/Redis
   (`docker-compose.test.yml` déjà présent) pour confirmer que la base
   P11 tient toujours à 80% de couverture.
3. Revue manuelle des 7 fichiers backend divergents listés ci-dessus avant
   toute décision de les intégrer.
