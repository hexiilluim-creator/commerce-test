# AutoCommerce — Livraison Ready-to-Go Tunisie

## Décision produit

La boutique est configurée pour la **Tunisie**. Le pays est cohérent avec le dinar tunisien (TND), les numéros téléphoniques `+216`, le lien WhatsApp et les données de démonstration existantes.

La boutique publique de référence est :

```text
http://localhost:5173/store/demo-store
```

En déploiement réel, cette URL doit être remplacée par le domaine public de la boutique.

## Route catalogue retenue

La route utilisée par la boutique frontend est la route canonique suivante :

```text
GET /api/v1/storefront/{store_id}/products
```

Pour la boutique de démonstration, elle est accessible avec `store_id=1` et renvoie actuellement six produits visibles, avec prix, stocks et pagination.

La route historique suivante n’a pas été supprimée afin de préserver la compatibilité et la traçabilité :

```text
GET /api/v1/products/public?store_id=1
```

Elle est désormais **en quarantaine**. Elle renvoie `410 Gone`, l’en-tête `X-Deprecated-Route: true` et un lien `rel="canonical"` vers la route storefront officielle. Aucun appel frontend de la boutique ne doit utiliser cette route historique.

## Parcours validé

Le parcours public suivant a été vérifié : affichage de la boutique, affichage des six produits, affichage des prix en TND, affichage des stocks, filtrage par catégorie, ajout au panier, consultation du panier, contrôle d’un formulaire incomplet et création d’une commande de test.

Le parcours administrateur a également été vérifié : connexion, tableau de bord, catalogue produits, commandes, rendez-vous, conversations, liens de paiement, paramètres, déconnexion et contrôle CSRF.

## Contrôles de livraison

| Contrôle | Résultat |
|---|---|
| Healthcheck backend | OK, HTTP 200 |
| Catalogue storefront canonique | OK, HTTP 200, 6 produits |
| Route historique en quarantaine | OK, HTTP 410, lien canonique présent |
| Boutique web | OK, HTTP 200 |
| Panier web | OK, HTTP 200 |
| TypeScript frontend | OK |
| Build Vite frontend | OK |
| Tests frontend | OK, 14 fichiers et 160 tests réussis |
| Redis et PostgreSQL | Déjà validés dans l’environnement de recette |
| Migrations Alembic | Déjà appliquées dans l’environnement de recette |

## Commandes de démarrage locales

Backend :

```bash
cd api-server
set -a; . ./.env.development; set +a
export ENV=development DEBUG=true SKIP_LIMITER=1 DISABLE_RATE_LIMIT=1
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

Frontend :

```bash
cd autocommerce-app
npm ci --legacy-peer-deps
npm run dev -- --host 0.0.0.0
```

## Conditions de mise en production réelle

Cette livraison est prête pour une mise en staging ou un déploiement contrôlé. Avant d’ouvrir le trafic public, il faut renseigner les secrets de production, activer HTTPS, connecter WhatsApp Business si ce canal est requis, configurer le prestataire de paiement en mode sandbox puis réel, vérifier les sauvegardes PostgreSQL, activer les journaux et alertes, et repartir d’une base de production sans commande de démonstration.

Aucun paiement réel n’a été déclenché pendant les tests. La commande de recette `#1` est une donnée de test et doit être supprimée ou archivée avant l’initialisation de la base de production.

## Décision de livraison

> **Version acceptée pour staging et recette finale. Version prête à déployer techniquement, sous réserve de renseigner les secrets et intégrations de production.**

La route catalogue, la vitrine tunisienne, le panier et la création de commande sont opérationnels. L’ancienne route est conservée en quarantaine et ne peut plus fournir un catalogue divergent.

Auteur : **Manus AI**
Date : **12 août 2026**

## Références internes

- `api-server/api/v1/storefront.py` — route storefront canonique.
- `api-server/api/v1/stock.py` — route historique mise en quarantaine.
- `autocommerce-app/src/pages/StorefrontPageV2.jsx` — appel frontend du catalogue canonique.
- `autocommerce-app/src/components/OptimizedCartV2.jsx` — panier et création de commande.
- `autocommerce-app/src/pages/StorefrontCartPage.jsx` — page panier publique.
- `READY_TO_GO_TUNISIE.md` — présent document.
