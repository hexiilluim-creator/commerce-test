# AutoCommerce — Configuration multi-pays et multi-devises

## Décision produit

AutoCommerce n’est plus limité à la Tunisie. Chaque boutique possède désormais sa propre configuration de localisation : pays, devise de règlement, langue et fuseau horaire. La Tunisie reste la configuration de démonstration par défaut avec `TN`, `TND`, `fr` et `Africa/Tunis`.

## Pays et devises disponibles

La configuration actuelle propose notamment la Tunisie, le Maroc, l’Algérie, la France, l’Allemagne, l’Italie, l’Espagne, la Belgique, les États-Unis, le Canada, le Royaume-Uni, les Émirats arabes unis, l’Arabie saoudite, le Sénégal et la Côte d’Ivoire. Les devises disponibles sont `TND`, `MAD`, `DZD`, `EUR`, `USD`, `CAD`, `GBP`, `AED`, `SAR` et `XOF`.

Le backend valide la devise choisie. Une valeur inconnue telle que `ZZZ` est rejetée avec une réponse HTTP 422. Les paramètres sont persistés par boutique et ne modifient pas les autres tenants.

## Propagation de la configuration

La configuration de boutique est utilisée par les paramètres, la vitrine publique, les cartes produits, le panier, les commandes, les messages sociaux, les dashboards principal, CEO et Commercial, la fidélité, les services de rendez-vous et le calculateur ROI lorsqu’il reçoit une boutique.

Le formatage monétaire est centralisé dans `autocommerce-app/src/utils/currency.js` et utilise `Intl.NumberFormat` avec la locale et le nombre de décimales adaptés à la devise. Les prix de la vitrine et du catalogue suivent la devise de la boutique. La clé de cache storefront est également liée à la configuration monétaire afin d’éviter qu’un ancien prix formaté soit servi après un changement de devise.

## Parcours de configuration marchand

Depuis `Settings > Boutique`, le marchand peut choisir la langue, le pays, la devise et le fuseau horaire, puis sauvegarder. Le dashboard recharge ces valeurs et les montants sont présentés dans la devise sélectionnée. Le changement est réversible et ne crée pas de donnée de test permanente.

## Preuves de validation

Le scénario synthétique suivant a été exécuté avec restauration finale de la boutique en Tunisie :

| Contrôle | Résultat |
|---|---|
| Lecture de la configuration TN/TND | PASS |
| Devise inconnue `ZZZ` rejetée | PASS, HTTP 422 |
| Changement temporaire vers FR/EUR | PASS, HTTP 200 |
| Vitrine FR/EUR | PASS |
| Produit affiché en EUR après invalidation/rotation du cache | PASS |
| Restauration TN/TND | PASS |
| Déconnexion après scénario | PASS |
| Build frontend | PASS |
| Typecheck | PASS |
| Tests frontend | PASS, 14 fichiers / 160 tests |
| Compilation backend Python | PASS |

## Limites à traiter avant production globale

La devise est correctement propagée pour l’affichage et le parcours de boutique. Les règles fiscales, les taux de change entre devises, les moyens de paiement disponibles par pays, les formats d’adresse, les numéros de téléphone, les taxes locales et les règles de facturation doivent encore être configurés ou validés selon chaque marché avant activation commerciale.

Les tarifs d’abonnement AutoCommerce et les crédits de la page marketing restent des tarifs de plateforme ; ils ne doivent pas être confondus avec la devise de règlement des produits d’une boutique. Une future version pourra les gérer séparément avec un catalogue de prix par marché.

## Configuration de démonstration conservée

La boutique de démonstration reste configurée ainsi :

| Paramètre | Valeur |
|---|---|
| Pays | Tunisie (`TN`) |
| Devise | Dinar tunisien (`TND`) |
| Langue | Français (`fr`) |
| Fuseau horaire | `Africa/Tunis` |

Cette configuration peut être modifiée par le marchand depuis l’écran Paramètres sans modifier les autres boutiques.

## Fichiers principaux modifiés

Les points d’implémentation sont la migration Alembic `0066_merge_heads_add_store_currency.py`, le modèle et les paramètres backend, la vitrine et son cache, le contexte boutique frontend, l’utilitaire `utils/currency.js`, les dashboards, le panier, les commandes, les produits, les messages sociaux, la fidélité, les rendez-vous et le calculateur ROI.

Le document ne constitue pas une validation automatique des paiements, taxes ou obligations réglementaires de chaque pays. Ces éléments doivent être acceptés par le responsable métier et les prestataires concernés avant activation dans un nouveau marché.

## Conclusion

La base technique est maintenant multi-pays, multi-devises et compatible avec le multilingue existant. La boutique tunisienne reste stable et reproductible ; un marchand peut choisir un autre pays, une autre devise, une autre langue et un autre fuseau depuis son propre dashboard.
