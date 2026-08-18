# Audit AutoCommerce — vérification et corrections

**Projet audité :** `/home/ubuntu/autocommerce-build`

**Source comparée :** `pasted_content.txt` fourni par l’utilisateur.

## Conclusion exécutive

Le rapport fourni décrivait correctement plusieurs défauts présents dans l’archive. Les trois anomalies les plus importantes ont été reproduites statiquement dans le code : le tunnel de commande directe n’avait pas de route backend, le tableau des commandes avait un en-tête de six colonnes pour sept cellules de données, et le panier moyen CEO était calculé sur le chiffre d’affaires encaissé au lieu du chiffre d’affaires brut. Ces points ont été corrigés dans le projet.

La correction a ensuite été revalidée par le build frontend, le typage TypeScript, la syntaxe Python, les 160 tests Vitest et les tests backend ciblés. La stack PostgreSQL/Redis complète n’a pas pu être démarrée dans cet environnement, car Docker, `.env.prod` et les certificats de production ne sont pas disponibles. Les migrations devront donc être appliquées et vérifiées sur une base PostgreSQL réelle avant déploiement final.

## Anomalies vérifiées et corrigées

| Domaine | Vérification dans l’archive | Correction appliquée | État |
|---|---|---|---|
| Tunnel de commande directe | Le frontend actuel ne comportait pas de bouton de commande directe et `api/v1/storefront.py` ne comportait pas `POST /{store_id}/orders`. | Ajout de `POST /api/v1/storefront/{store_id}/orders`, validation de la boutique et des produits, reprise des prix depuis la base, application promotions/taxes, création client/commande et retour de confirmation. Ajout du bouton dans `OptimizedCartV2.jsx`. | Corrigé statiquement ; test runtime PostgreSQL à faire |
| Sécurité du prix commande | Le navigateur pouvait être la seule source apparente du prix dans le futur parcours direct. | Les prix transmis sont ignorés pour le calcul final : les produits actifs sont relus par `store_id` et `product_id`, puis le prix serveur est utilisé. | Corrigé |
| CSRF storefront | Une mutation publique storefront aurait été bloquée par le middleware CSRF même après ajout de la route. | Ajout de l’exemption ciblée `/api/v1/storefront/`, la route restant protégée par validation serveur et limites de payload. | Corrigé |
| Tableau des commandes | `Orders.jsx` avait six en-têtes mais sept cellules : ID, client, statut, canal, total, date, actions. Le serializer backend ne renvoyait ni `delivery_name` ni `channel`. | Ajout des colonnes Client et Canal, correction des `colSpan`, ajout de `orders.channel`, migration Alembic `0065_add_order_channel.py`, sérialisation et persistance de `delivery_name`/`channel`. | Corrigé |
| Dashboard CEO | `avg_order` était calculé comme `ca_now / orders_now`, alors que `ca_now` ne comprenait que les statuts payés. `revenue_paid_tnd` était absent. | Le backend calcule le CA brut, le CA encaissé et le panier moyen sur le CA brut. Ajout de `revenue_paid_tnd`, des montants payés dans `revenue` et affichage distinct dans `DashboardCEO.jsx`. | Corrigé |
| RLS / portée transactionnelle | `tenant_session()` exécutait `SET LOCAL` dans un bloc transactionnel fermé avant le `yield`, ce qui pouvait supprimer le contexte avant les requêtes métier. | Passage à `set_config(..., false)` avec nettoyage explicite. `get_db()` et le hook de pool réinitialisent les GUC afin d’éviter toute fuite inter-tenant. | Corrigé statiquement ; test PostgreSQL réel requis |
| Policies RLS append-only | Le test statique ne trouvait pas les noms de policies car ils étaient construits uniquement par f-string. | Noms explicites pour `audit_logs_select`, `audit_logs_insert`, `credit_events_select` et `credit_events_insert`. | Corrigé ; test RLS passe |
| Langues i18n | Le sélecteur affichait espagnol et italien alors que `i18n/index.js` ne chargeait que fr/en/ar/de. | Retrait de ES et IT du sélecteur. | Corrigé |
| Pagination storefront | Le frontend envoyait `offset`, ignoré par le backend qui utilise une pagination par curseur. | Utilisation de `next_cursor`/`has_more` dans `StorefrontPageV2.jsx`. | Corrigé |
| Tests Vitest | `@testing-library/dom` manquait et `vi` n’était pas importé dans `src/tests/setup.ts`; un accès à `Error.code` était mal typé. | Ajout de la dépendance, import de `vi` et correction du typage. | Corrigé |

## Fichiers principaux modifiés

- `autocommerce-app/src/components/OptimizedCartV2.jsx`
- `autocommerce-app/src/pages/Orders.jsx`
- `autocommerce-app/src/pages/DashboardCEO.jsx`
- `autocommerce-app/src/pages/StorefrontPageV2.jsx`
- `autocommerce-app/src/components/LanguageSwitcher.jsx`
- `autocommerce-app/src/i18n/fr.json`
- `autocommerce-app/src/i18n/en.json`
- `autocommerce-app/src/i18n/ar.json`
- `autocommerce-app/src/i18n/de.json`
- `autocommerce-app/src/tests/setup.ts`
- `autocommerce-app/package.json` et `package-lock.json`
- `api-server/api/v1/storefront.py`
- `api-server/api/v1/orders.py`
- `api-server/api/v1/dashboard_enterprise.py`
- `api-server/models/database.py`
- `api-server/models/database.py`
- `api-server/services/tenant_db_context.py`
- `api-server/middleware/csrf_protection.py`
- `api-server/alembic/versions/0058_enforce_rls_and_harden_credit_events.py`
- `api-server/alembic/versions/0065_add_order_channel.py`

## Résultats de validation

| Vérification | Résultat |
|---|---|
| `npm run typecheck` | Réussi, aucune erreur TypeScript |
| `NODE_ENV=production npm run build` | Réussi, bundle Vite généré dans `dist/public` |
| Tests Vitest | **160/160 réussis**, 14 fichiers de test |
| Syntaxe backend Python | Réussie avec `compileall` |
| Tests backend auth + CSRF + RLS ciblés | **116 réussis, 1 ignoré** |
| Avertissements tests backend | Un avertissement `pytest.mark.dbtest` non enregistré, sans échec fonctionnel |
| Vérification publique frontend | HTTP 200, titre `AutoCommerce` |

## Points qui restent à valider en environnement de production réel

Le code est corrigé et les validations statiques/unitaires passent, mais les éléments suivants nécessitent PostgreSQL, Redis et les variables de production réelles :

1. Appliquer `alembic upgrade head`, notamment la migration `0065_add_order_channel.py`.
2. Tester réellement `POST /api/v1/storefront/{store_id}/orders` avec une boutique, un produit en stock, une promotion et une transaction PostgreSQL.
3. Vérifier l’isolation RLS sur deux tenants dans PostgreSQL avec le pool de connexions actif.
4. Exécuter les tests E2E storefront et rendez-vous avec l’API, PostgreSQL et Redis démarrés.
5. Fournir `.env.prod`, les certificats et Docker pour démarrer la stack complète `docker-compose.prod.yml`.

## Accès frontend corrigé

Le frontend compilé et exposé reste accessible ici : [ouvrir AutoCommerce](https://4173-is340bxymuv1yxphea7jx-e77a7bb2.us2.manus.computer/).

Le serveur public actuel sert le dernier bundle corrigé et répond en HTTP 200.
