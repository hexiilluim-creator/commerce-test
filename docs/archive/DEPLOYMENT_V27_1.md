# Guide de déploiement AutoCommerce Enterprise V28

> Ce runbook couvre la mise en production d'un environnement vierge.
> Chaque étape doit être exécutée dans l'ordre. Ne pas sauter d'étape.

## Prérequis

- Docker Engine ≥ 24, Docker Compose v2
- Un serveur Linux avec ≥ 8 Go RAM, ≥ 50 Go disque
- Domaines DNS configurés et pointant vers le serveur
- Certificats TLS (voir `certs/README.txt`)
- **Aucun secret ne doit venir de cette archive** (voir section Secrets)

---

## Étape 0 — Règle absolue avant tout déploiement

> **INTERDICTION** : ne jamais déployer un package contenant un fichier `.env` peuplé.
> Tout `.env.*` (hors `.example`) présent dans l'archive est un incident de sécurité.

```bash
# Vérification anti-secrets — BLOQUANT
bash scripts/release_gate.sh .
# Doit retourner exit code 0 et "PASS" sur tous les contrôles
```

Si `release_gate.sh` échoue : arrêt du déploiement. Ne pas contourner.

---

## Étape 1 — Génération des secrets côté serveur cible uniquement

```bash
# Sur le serveur cible, PAS sur votre poste de développement
bash scripts/generate_secrets.sh > .env.prod

# Compléter les valeurs manquantes (domaines, clés API externes, etc.)
nano .env.prod

# Vérifier que tous les secrets critiques sont présents
bash scripts/check_compose_prod.sh .env.prod
# → Doit retourner PASS sur tous les contrôles

# Vérifier le preflight applicatif
ENV=production python3 api-server/preflight_secrets.py
# → Doit retourner "Tous les secrets critiques sont présents"
```

**Si ces secrets ont déjà été distribués dans une version précédente** :
1. Les révoquer immédiatement sur toutes les plateformes concernées
2. Générer de nouveaux secrets avec `generate_secrets.sh`
3. Ne jamais réutiliser un secret qui a transité dans un fichier versionné

---

## Étape 2 — Bootstrap infrastructure

```bash
# Démarrer les services d'infrastructure uniquement (DB + Redis)
docker compose -f docker-compose.prod.yml up -d postgres redis

# Attendre que PostgreSQL soit healthy
docker compose -f docker-compose.prod.yml ps
# postgres doit afficher "(healthy)"
```

---

## Étape 3 — Migration de base de données

```bash
# Migration Alembic (une seule fois, ou à chaque upgrade)
docker compose -f docker-compose.prod.yml run --rm api \
  python3 -m alembic upgrade head

# Application du script RLS complet (CRITIQUE)
docker compose -f docker-compose.prod.yml run --rm api \
  psql "$DATABASE_URL" -f /app/sql/RLS_POLICIES.sql

# Vérification RLS
docker compose -f docker-compose.prod.yml run --rm api \
  psql "$DATABASE_URL" -c "
    SELECT relname, relrowsecurity, relforcerowsecurity
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r'
    ORDER BY relname;
  "
# → Toutes les tables multi-tenant doivent avoir t/t
```

---

## Étape 4 — Démarrage de l'application

```bash
# Démarrer l'API et le worker Celery
docker compose -f docker-compose.prod.yml up -d api celery

# Vérifier le healthcheck
curl -fsS http://localhost:8000/api/health
# → {"status": "ok"}
```

---

## Étape 5 — Démarrage du frontend et Nginx

```bash
docker compose -f docker-compose.prod.yml up -d frontend nginx

# Vérifier que Nginx est actif
curl -I https://<votre-domaine>/
# → HTTP 200

# Vérifier les headers de sécurité
curl -I https://<votre-domaine>/api/health | grep -i "content-security-policy"
# → Doit contenir nonce-... SANS unsafe-inline
# → Un seul header CSP (pas de doublon)
```

---

## Étape 6 — Smoke tests post-déploiement

```bash
# Tests de sécurité (nécessite accès à la DB cible)
TEST_DATABASE_URL="$DATABASE_URL" \
  pytest api-server/tests/security/test_p0_p1_enterprise_controls.py -v
# → Tous les tests doivent passer

# Test d'isolation cross-tenant (manuel)
# 1. Créer deux stores de test
# 2. S'authentifier avec le token du store B
# 3. Tenter d'accéder aux données du store A
# 4. Vérifier que la réponse est vide ou 403
```

---

## Étape 7 — Changement des mots de passe initiaux

```bash
# Changer immédiatement les mots de passe admin/superadmin
docker compose -f docker-compose.prod.yml run --rm api \
  python3 reset_passwords.py \
    --admin-email admin@<votre-domaine> \
    --new-password <nouveau-mot-de-passe-fort>
```

**Ne jamais utiliser `ADMIN_INITIAL_PASSWORD` en production au-delà de cette étape.**

---

## Étape 8 — Backup initial

```bash
# Vérifier que la stratégie de backup est opérationnelle
bash scripts/backup_pg.sh

# Tester le restore
bash scripts/restore_pg.sh --dry-run
```

---

## Checklist finale avant ouverture

Chaque item doit être signé par ops + sécurité avant d'ouvrir au trafic.

- [ ] `release_gate.sh` : PASS (aucun secret dans l'artefact)
- [ ] `check_compose_prod.sh` : PASS (configuration compose valide)
- [ ] `preflight_secrets.py` : PASS (tous les secrets présents)
- [ ] Migration Alembic exécutée avec succès
- [ ] `RLS_POLICIES.sql` exécuté — toutes les tables ont `relrowsecurity=t` et `relforcerowsecurity=t`
- [ ] Tests de sécurité : 100% PASS
- [ ] Headers CSP vérifiés : nonce présent, `unsafe-inline` absent, un seul header CSP
- [ ] Mots de passe initiaux changés
- [ ] Backup initial réalisé et restore testé
- [ ] Supervision et alerting actifs
- [ ] Rotation des secrets planifiée (JWT, chiffrement, etc.)

**Signé par ops** : _________________________ Date : _________

**Signé par sécurité** : _____________________ Date : _________

---

## Rotation des secrets

En cas de compromission suspectée, procéder dans cet ordre :

1. Générer de nouveaux secrets sur le serveur cible
2. Mettre à jour `.env.prod` (jamais versionné)
3. Redémarrer l'API : `docker compose restart api celery`
4. Invalider toutes les sessions actives (JWT rotation)
5. Documenter l'incident

```bash
# Rotation JWT (invalide toutes les sessions)
docker compose -f docker-compose.prod.yml run --rm api \
  python3 services/jwt_rotation.py --rotate-now
```
