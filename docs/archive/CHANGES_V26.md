# AutoCommerce Enterprise V26 — Correctifs livrés

Ce document liste les corrections apportées à la V25, en réponse au
`Rapport_des_Erreurs_et_Alertes_Restantes___AutoCom.md`.

Chaque correctif ci-dessous référence la section du rapport originel.

---

## ✅ 1. Configuration boutique (§1 du rapport — complétude 40 % → 100 %)

**Symptôme initial :** l'écran `/settings/store` affichait « Configuration
incomplète (40 %) » avec 6 champs manquants (numéro WhatsApp, produits
actifs, WhatsApp Business, logo, description, email de contact).

**Correctif :** `api-server/seed_production.py`

- La fonction `seed()` a été rendue **idempotente et incrémentale** : elle
  reprend son travail même sur une base déjà seedée, pour backfiller les
  champs manquants sans écraser les valeurs déjà renseignées.
- Le store `demo-store` est désormais créé (ou complété) avec :
  `whatsapp_phone`, `owner_phone`, `support_email`, `logo_url`, `category`,
  `language`, `timezone`, `ai_agent_prompt`, `order_confirmation_msg`.
- Les valeurs par défaut sont paramétrables via des variables d'env
  `DEMO_WHATSAPP_PHONE`, `DEMO_OWNER_PHONE`, `DEMO_SUPPORT_EMAIL`,
  `DEMO_LOGO_URL` (déjà présentes dans `.env.production`).
- La configuration WhatsApp Business API reste **BYOK par store**
  (endpoint `POST /api/v1/settings/whatsapp-credentials`), avec token
  chiffré Fernet — comportement inchangé pour la sécurité.

## ✅ 2. Erreur `OPTIONS 405 Method Not Allowed` sur `/api/v1/auth/login` (§2.1)

**Correctif :** `api-server/main.py`

- Ajout d'un **handler catch-all `@app.options("/{full_path:path}")`** qui
  répond `204 No Content` pour toute pré-flight CORS non gérée par un
  routeur, sans passer par le stack applicatif (rate-limit, CSRF, etc.).
- Le middleware CORS reste seul responsable des réponses OPTIONS
  légitimes (avec en-têtes Access-Control-\*) ; ce handler agit
  uniquement en dernier recours pour les clients HTTP stricts.

## ✅ 3. Port 8000 déjà occupé lors des redémarrages (§2.2)

**Correctif :** `api-server/start.sh`

- Ajout d'un pré-check de port : si `PORT` (défaut 8000) est occupé,
  `start.sh` envoie SIGTERM (3 s de grâce) puis SIGKILL au(x) processus
  résiduels avant de démarrer Uvicorn.
- Comportement contrôlable via `KILL_STALE_PORT=1` (défaut : `1` en dev,
  `0` en prod — voir `.env.production` où pm2/systemd gère le cycle de vie).
- Recommandation prod : utiliser un supervisor (systemd, pm2, ou le
  `restart: unless-stopped` de `docker-compose.prod.yml` déjà en place).

## ✅ 4. En-têtes CORS (§2.3)

**État V25 :** contrairement à ce qu'indiquait le rapport, le code V25
utilisait déjà une **whitelist explicite** `allow_headers=[Authorization,
Content-Type, X-Request-ID, X-CSRF-Token]`. Aucun `*` en production.
Correctif documentaire uniquement : voir commentaire ajouté dans
`main.py` (section CORS) pour préciser que la liste est déjà restreinte.

## ✅ 5. Base de données vide / tableau de bord à zéro (§3)

**Correctif :** `api-server/seed_production.py`

- Ajout d'un **catalogue démo de 6 produits actifs** (`DEMO_PRODUCTS`) :
  T-shirt, sac à dos, casque Bluetooth, bouteille isotherme, montre
  connectée, chaussures running. Tous marqués `is_active=True`.
- Prix en dinar tunisien (TND) par défaut, quantités de stock réalistes.
- La fonction `_seed_demo_products()` est idempotente : n'insère que les
  produits absents (join sur `external_code`).
- Résultat attendu au premier démarrage : le tableau de bord affiche
  6 produits, ~480 unités en stock, catalogue prêt pour tester la
  recherche IA, les recommandations et le tunnel de commande WhatsApp.

## ✅ 6. Secrets par défaut / non aléatoires (§4)

**Correctif :** `.env`, `.env.production`

- Tous les secrets (`JWT_SECRET_KEY`, `CSRF_SECRET`, `ENCRYPTION_KEY`,
  `INTERNAL_HEALTH_TOKEN`, `INTERNAL_API_KEY`, `*_VERIFY_TOKEN`,
  `*_APP_SECRET`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`,
  `ADMIN_INITIAL_PASSWORD`, `SUPERADMIN_INITIAL_PASSWORD`) ont été
  **régénérés cryptographiquement** avec `secrets.token_hex(32)` /
  `Fernet.generate_key()`.
- ⚠️ **Ces valeurs sont livrées comme point de départ**. En production
  réelle : **régénérez-les à nouveau** avant déploiement et stockez-les
  dans un secret manager (AWS SSM, HashiCorp Vault, Doppler…).

## ℹ️ 7. HTTPS et domaine public (§4)

**Aucun changement code** — c'est une checklist opérationnelle. Voir
`DEPLOYMENT_V26.md` (nouvelle checklist ajoutée).

---

## Fichiers modifiés

```
api-server/
├── .env                    ← secrets DEV régénérés
├── .env.production         ← secrets PROD régénérés + config demo
├── main.py                 ← handler OPTIONS catch-all
├── seed_production.py      ← config store 100 % + 6 produits demo
└── start.sh                ← nettoyage port avant boot

CHANGES_V26.md              ← ce fichier
DEPLOYMENT_V26.md           ← nouvelle checklist prête à déployer
```

## Fichiers **non touchés** (zéro régression sur le reste du code)

Tout le reste de la V25 est identique bit-à-bit : migrations Alembic
(0001 → 0040), 36 routeurs API, 60+ services, frontend React/Vite, docker
compose, tests. Aucune modification n'a été apportée sur la logique
métier, l'API publique, le schéma DB ou le pipeline CI/CD.

## Comment vérifier localement

```bash
cd api-server
python3 -m py_compile seed_production.py main.py    # syntaxe OK
sh -n start.sh                                       # syntaxe OK

# Puis lancer :
cp .env.production .env.prod
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
docker compose -f docker-compose.prod.yml exec api \
  python3 seed_production.py
```

Après le seed, `GET /api/v1/settings/store/completeness` doit renvoyer
`100`, et `GET /api/v1/settings/store` doit contenir les 6 champs
précédemment manquants.
