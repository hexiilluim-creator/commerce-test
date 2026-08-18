# AutoCommerce Enterprise V28.2.2 — Release finale corrigée

## Contenu

Cette archive contient le code source frontend et backend, le build frontend de production dans `autocommerce-app/dist/public`, les migrations Alembic, les tests, les Dockerfiles, les fichiers Compose, les verrous de dépendances et la documentation utile au déploiement.

Les environnements virtuels, `node_modules`, fichiers `.env` locaux, logs, PID, rapports de couverture et autres artefacts propres à l’environnement de test ont été exclus. Les variables sensibles doivent être renseignées dans des fichiers d’environnement locaux non versionnés avant déploiement.

## Corrections intégrées dans cette version

- Ajout du contexte RLS temporaire et limité aux endpoints d’authentification afin que `login` puisse rechercher un utilisateur et que `register` puisse créer le premier tenant sous `FORCE ROW LEVEL SECURITY`.
- Correction du contexte tenant de la vitrine publique avant lecture du catalogue, calcul promotionnel, calcul fiscal et création de commande.
- Configuration CORS explicite compatible avec l’origine frontend et les cookies HttpOnly lorsque frontend et backend sont exposés sur des domaines distincts.
- Correction de l’attente du client Redis asynchrone dans le flux storefront.
- Encodage JSON des `Decimal` dans les articles, taxes et promotions des commandes publiques.
- Suppression du refresh ORM post-commit qui pouvait provoquer un faux HTTP 500 après persistance réussie de la commande sous RLS.
- Affichage du canal `storefront` sous la forme `🛍️ Web` dans le tableau Orders.
- Conservation des corrections précédentes : colonnes Client/Canal, migration `orders.channel`, KPI CEO séparant CA brut et CA encaissé, pagination storefront par curseur, setup Vitest et sélecteur de langues cohérent.

## Vérifications réalisées

- Build Vite de production réussi.
- Typage TypeScript réussi.
- Compilation syntaxique Python réussie.
- Frontend public : HTTP 200.
- Backend `/health` : HTTP 200.
- Catalogue storefront : HTTP 200, produits visibles.
- Parcours navigateur : vitrine, ajout au panier, commande directe et confirmation.
- Authentification admin : connexion et redirection dashboard réussies.
- Orders : commandes, client et canal Web affichés.
- Dashboard CEO : CA brut, CA encaissé, valeur moyenne et conversion affichés.
- Aucun secret réel ni certificat privé inclus dans l’archive.

## Démarrage

Pour le frontend :

```bash
cd autocommerce-app
npm ci
npm run build
npm run serve -- --host 0.0.0.0 --port 4173
```

Pour le backend, créer d’abord un environnement Python et renseigner les variables requises selon `.env.example`, puis installer les dépendances :

```bash
cd api-server
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
alembic upgrade heads
uvicorn main:app --host 0.0.0.0 --port 8001
```

La validation PostgreSQL/Redis réelle, les clés Meta/WhatsApp, les fournisseurs de paiement et les services IA externes doivent être configurés séparément pour un environnement de production.
