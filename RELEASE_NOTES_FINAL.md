# AutoCommerce Enterprise V28.2.1 — Release finale corrigée

Cette archive contient la version finale corrigée et vérifiée d’AutoCommerce Enterprise. Elle inclut le code source frontend/backend, le build frontend de production déjà généré, les migrations Alembic, les fichiers Docker/Compose, les tests, les scripts d’exploitation et la documentation.

## Vérifications effectuées

- `npm run typecheck` : réussi.
- `NODE_ENV=production npm run build` : réussi.
- Tests Vitest : **160/160 réussis**.
- Tests backend ciblés auth, CSRF et RLS : **116 réussis, 1 ignoré**.
- Compilation syntaxique Python backend : réussie.
- Build servi publiquement : HTTP 200, titre `AutoCommerce`.

## Corrections incluses

La commande directe storefront, la persistance du canal de commande, l’alignement du tableau Orders, les KPI CEO, le contexte RLS, l’exemption CSRF storefront, la pagination par curseur, le sélecteur de langues et les erreurs Vitest ont été corrigés. Le détail complet se trouve dans `AUDIT_VERIFICATION_CORRECTIONS.md`.

## Démarrage frontend déjà compilé

Le build prêt à servir se trouve dans `autocommerce-app/dist/public`.

```bash
cd autocommerce-app
npm install
npm run serve -- --port 4173
```

## Démarrage du backend

```bash
cd api-server
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.production.example .env
# Renseigner les variables de production sans committer le fichier .env.
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8000
```

La migration `0065_add_order_channel.py` doit être appliquée avec `alembic upgrade head` avant l’utilisation des nouvelles colonnes de commande.

## Déploiement Docker

Les fichiers `docker-compose.prod.yml`, `nginx.conf`, `nginx.tls.conf.example`, les Dockerfiles et les scripts de déploiement sont inclus. Les secrets, certificats réels, mots de passe et fichiers `.env` ne sont volontairement pas inclus dans cette livraison.

> La validation complète avec PostgreSQL, Redis, certificats et variables de production réelles doit être exécutée sur l’environnement cible avant mise en production définitive.
