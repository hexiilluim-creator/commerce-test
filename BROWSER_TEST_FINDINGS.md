# Résultats de test navigateur — déploiement vierge

URL frontend publique : https://4174-is340bxymuv1yxphea7jx-e77a7bb2.us2.manus.computer/

URL vitrine testée : https://4174-is340bxymuv1yxphea7jx-e77a7bb2.us2.manus.computer/store/demo-store?fresh=2051

URL API publique : https://8001-is340bxymuv1yxphea7jx-e77a7bb2.us2.manus.computer/

Résultats observés : la page vitrine affiche `Demo Store`, la bannière « Bienvenue dans notre boutique ! », l’état « Ouvert », le bouton WhatsApp, les catégories et 11 produits de démonstration avec prix et stock. Le catalogue inclut notamment Coque iPhone, Samsung S24 Ultra, AirPods Pro 2, MacBook Air M2 et iPhone 15 Pro. Les boutons « Ajouter » sont visibles pour les produits disponibles.

Diagnostic runtime initial : les produits étaient masqués par FORCE RLS pour la route publique, le CORS wildcard était incompatible avec Axios `withCredentials`, et le cache storefront appelait `get_redis()` sans attendre sa coroutine. Ces trois blocages ont été corrigés dans l’environnement de déploiement vierge : contexte tenant public après résolution du store, CORS explicite avec credentials lorsque `CORS_ORIGINS` est renseigné, et attente correcte du client Redis async.

Après redéploiement du backend, l’API catalogue répond HTTP 200 avec des produits et le navigateur rend la vitrine complète.

## Parcours panier et commande

Le produit `Coque iPhone` a été ajouté au panier depuis la vitrine. Le panier a affiché 1 article, le sous-total et le total de 50.000 DT, ainsi que les champs nom/téléphone et les canaux WhatsApp/commande directe.

Le premier envoi avec `+21620000001` a persisté une commande mais a renvoyé HTTP 500 lors du refresh RLS post-commit ; ce faux échec a été corrigé en supprimant le refresh immédiat après commit. Une seconde commande confirmée avec `+21620000002` a ensuite réussi dans l’interface : `Commande #5 enregistrée. Nous vous contacterons pour confirmer la livraison.`

## Parcours authentifié

La connexion `admin@autocommerce.tn` a d’abord renvoyé 401 car la table users était masquée par FORCE RLS pendant le login. Le contexte RLS dédié aux endpoints auth a été ajouté, puis la connexion a réussi et a redirigé vers `/dashboard` avec le rôle `admin`.

Le Dashboard général affiche les commandes historiques et les deux commandes de test. La page `/orders` affiche 5 commandes et les colonnes `#`, `Client`, `Status`, `Channel`, `Total`, `Date`, `Actions`; les commandes de test apparaissent avec `Client Test AutoCommerce` et le statut `Confirmed`.

Le Dashboard CEO s’affiche avec les KPI corrigés : CA brut `9,300 TND`, encaissé `8,350 TND`, 5 commandes, valeur moyenne `1,860.00 TND`, conversion `40%`, ainsi que la répartition par statut.

## Vérifications finales

Après recompilation, le tableau Orders affiche les commandes directes avec `🛍️ Web` dans la colonne Canal. La valeur `storefront` est également confirmée en base pour les commandes 4 et 5.

Le sélecteur de langue expose uniquement FR, EN, AR et DE ; le bouton EN est bien présent dans le DOM. Le test visuel principal a été réalisé en français, avec maintien de la session admin pendant les navigations Dashboard, Orders et Dashboard CEO.
