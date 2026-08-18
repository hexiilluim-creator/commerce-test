# AutoCommerce Enterprise V27 — correctifs complémentaires

Cette version reprend la V26 fournie et termine les corrections restées incomplètes après audit technique.

## Correctifs livrés

- **Complétude boutique rendue cohérente**
  - backfill du champ `description` manquant dans `seed_production.py`
  - backfill des champs `language`, `timezone`, `ai_agent_prompt`, `order_confirmation_msg`
  - `public_url` corrigée vers `/store/{slug}` (route canonique du frontend)
  - vérification `WhatsApp Business configuré` renforcée : **token chiffré + phone_number_id** requis

- **Seed production réellement idempotent**
  - les produits démo existants sont désormais remis à niveau (`is_active`, prix, stock, description, tags)
  - possibilité de brancher de vraies credentials WhatsApp via `DEMO_WHATSAPP_ACCESS_TOKEN` / `DEMO_WHATSAPP_PHONE_NUMBER_ID`
    ou via les variables globales `WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID`

- **Client WhatsApp corrigé pour la prod**
  - déchiffrement du champ `whatsapp_access_token_enc` lors du build du client tenant-aware
  - fallback propre vers la config globale si aucune credential par store n'est fournie
  - ajout des méthodes manquantes `send_list_message()` et `send_image()` utilisées par Omnicall V9
  - garde-fou explicite si le client n'est pas configuré

- **Tests unitaires ajoutés**
  - couverture des cas critiques du client WhatsApp (déchiffrement, fallback, payloads, erreur de config)

## Impact attendu

- la boutique démo n'affiche plus une complétude trompeuse
- la mise en ligne réelle dépend maintenant explicitement de vraies credentials Meta
- les envois WhatsApp Omnicall n'échouent plus pour cause de méthodes absentes ou de token non déchiffré
