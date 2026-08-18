# FAQ utilisateur final — onboarding par canal

> Cible : marchands qui découvrent AutoCommerce après leur première connexion.
> Chaque section est indépendante — un marchand WhatsApp-only n'a pas besoin de lire la section IG.

## Sommaire

1. [WhatsApp Business](#1-whatsapp-business)
2. [Facebook Messenger](#2-facebook-messenger)
3. [Instagram DM](#3-instagram-dm)
4. [TikTok commentaires](#4-tiktok-commentaires)
5. [Questions transverses](#5-questions-transverses)

---

## 1. WhatsApp Business

### 1.1 Comment lier mon numéro WhatsApp ?
1. Allez dans **Paramètres → WhatsApp** dans le backoffice.
2. Scannez le QR code affiché avec l'appli WhatsApp Business sur votre téléphone.
3. Notre agent envoie un message test — quand vous le recevez, la liaison est active.

### 1.2 Combien de messages l'IA peut-elle envoyer par jour ?
La capacité dépend de votre plan :
- **Starter** : 200 réponses IA / jour
- **Business** : 1 000 réponses IA / jour
- **Premium / Pro WhatsApp** : 5 000+ réponses IA / jour

Au-delà, l'IA se met automatiquement en sourdine et vous pouvez répondre manuellement.

### 1.3 L'IA peut-elle envoyer des images, catalogues, ou liens de paiement ?
Oui. L'IA reconnaît automatiquement dans la conversation :
- **Photos / vidéos** : lien vers catalogue produit
- **Demande de prix** : lien Stripe / Paymee / D17 prêt à envoyer
- **Demande d'adresse** : renvoyé en geo-carte WhatsApp

### 1.4 Comment suspendre l'IA temporairement (live, démo, conflit) ?
- **Bouton noir** `:mute` côté backoffice → sourdine 30 minutes par défaut.
- **Depuis WhatsApp** : envoyez `!pause` au bot → sourdine 30 minutes.
- Pour plus de 30 minutes, ajustez le TTL via le curseur **« minutes »** dans l'admin.

### 1.5 Que se passe-t-il si WhatsApp est indisponible (outage Meta) ?
Notre **runbook d'incident** tombe automatiquement en mode dégradé : toutes les conversations sont mises en file d'attente et traitées dès le retour du service. Vous pouvez suivre l'état sur le dashboard.

---

## 2. Facebook Messenger

### 2.1 Comment brancher ma page Facebook ?
1. Créez une **app Meta for Developers** (gratuit) avec le produit **Messenger**.
2. Générez un **Page Access Token** (long-lived).
3. Collez ce token dans **Paramètres → Facebook** du backoffice.
4. Notre webhook se déclare automatiquement — validation Meta en moins de 30 secondes.

### 2.2 Puis-je utiliser Messenger sans Facebook Ads ?
Oui. Les conversations Messenger (DM entrant, commentaires→DM) sont supportées sans budget publicitaire. Les Ads sont optionnels.

### 2.3 Combien de pages puis-je brancher ?
- **Starter** : 1 page
- **Business** : jusqu'à 5 pages (utile pour franchises)
- **Enterprise** : illimité

### 2.4 Comment répondre en DM à un commentaire posté sur ma page ?
L'IA le fait automatiquement si elle a été configurée avec `comment_dm_enabled=true` dans **Paramètres → IA → Canaux**.

---

## 3. Instagram DM

### 3.1 Ai-je besoin d'un compte Instagram Business ?
Oui, indispensable pour utiliser l'API Graph. Passez votre compte en **Professional → Business** (gratuit depuis l'app Instagram).

### 3.2 Que se passe-t-il pour les DM si je suis en compte personnel ?
L'API officielle ne fonctionne pas — l'IA répondra uniquement aux **mentions / commentaires publics** (réponses limitado). Recommandation : passer en Business.

### 3.3 Limite de messages ?
- **Starter** : 200 DM / jour
- **Business / Premium** : 1 000 DM / jour
- **Enterprise** : 5 000 DM / jour, ajustable

### 3.4 Puis-je tagger un produit dans la réponse ?
Oui. Si l'IA détecte un produit pertinent dans sa réponse, elle attache automatiquement une **product tag** (image + prix + lien checkout) au DM.

---

## 4. TikTok commentaires

### 4.1 Comment relier TikTok ?
1. Demandez l'accès développeur via **TikTok for Developers** (formulaire en anglais, delai 1‑3 jours).
2. Créez une app avec les scopes `user.info.basic`, `video.list`, `comment.list`, `comment.write`.
3. Collez `client_id` + `client_secret` dans **Paramètres → TikTok**.

### 4.2 L'IA répond-elle aux commentaires TikTok en DM ?
**Non**. TikTok ne permet pas l'envoi de DM via API aux non-followers. L'IA reste cantonnée aux **commentaires publics** sur vos vidéos.

### 4.3 Modération automatique des commentaires toxiques ?
Oui. Activez **IA → Modération** dans le backoffice — l'IA masquera automatiquement les commentaires à score de toxicité > 0.8 (Perspective API compatible).

### 4.4 Limite ?
- 500 réponses / vidéo / jour (capacité API TikTok)
- 10 000 réponses / jour au total (compte Business vérifié)

---

## 5. Questions transverses

### 5.1 L'IA parle-t-elle d'autres langues que le français ?
Oui. Français, anglais, arabe dialectal Maghreb, espagnol, allemand sont supportés nativement. Détection automatique de la langue du client.

### 5.2 Combien coûte un crédit IA ?
- 1 crédit ≈ 1 000 tokens (≈ 750 mots)
- Une réponse type : 2-4 crédits
- Une conversation de 10 échanges : ~25 crédits

### 5.3 Comment acheter plus de crédits ?
**Paramètres → Crédits → Boutique de packs** : 50 / 200 / 500 / 1 000 crédits (25 / 80 / 175 / 300 DT). Paiement Stripe ou D17.

### 5.4 Puis-je exporter mes conversations ?
Oui. **Paramètres → RGPD → Exporter mes données** génère un ZIP JSON + CSV avec toutes vos conversations, commandes, et journal d'audit.

### 5.5 Où trouver le statut du service ?
- **Dashboard** → pastille verte dans le header (latence p95)
- **Status page** : https://status.autocommerce.example
- **Twitter** : [@autocommerce_saas](https://twitter.com/autocommerce_saas)

### 5.6 Que faire en cas d'urgence ?
1. Bouton d'urgence `:mute` côté backoffice (sourdine IA immédiate)
2. Support direct : support@autocommerce.example
3. Hotline entreprises (24/7) : numéro fourni dans votre contrat

> Voir aussi : [`runbook-incidents.md`](runbook-incidents.md), [`backup-restore-strategy.md`](backup-restore-strategy.md).
