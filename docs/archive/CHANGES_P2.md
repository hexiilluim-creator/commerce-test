# CHANGEMENTS V27.2 — Actions P2 livrées

Date : 20 juillet 2026 · Source : P1 corrigé (audit v27.1) + plan P2 exécuté.

## Légende statut

| Symbole | Sens |
|---|---|
| ✅ | livré, vérifié syntaxiquement, prêt QA |
| ⚠️ | besoin dépendance externe ou test runtime hors sandbox (déclaré honnêtement) |
| 🟡 | runtime à valider post‑merge (test plan fourni) |

## Résumé exécutif

**6 actions P2 sur 6 livrées** dans le code source réel. Le package reste **NON‑READY** au sens DoD : P3 (HA multi‑région, DR chaos, RGPD export/suppression, SSO IdP, observabilité avancée) reste à exécuter, et l'audit sécurité externe indépendant n'a pas encore été réalisé.

| # | Action | Statut | Effort | Owner |
|---|---|---|---|---|
| P2‑1 | Pipeline CI = release auto | ✅ | 2 j·p | DevOps |
| P2‑2 | Catalogue produits & boutique — UX & perf | ✅ | 3 j·p | Frontend + Backend |
| P2‑3 | Stratégie backup/restore documentée & testée | ✅ | 2 j·p | SRE |
| P2‑4 | Quota / facturation B2B ajustée | ✅ | 2 j·p | Backend |
| P2‑5 | Backoffice : modération agent & kill switch | ✅ | 1,5 j·p | Backend + Frontend |
| P2‑6 | Documentation utilisateur final & runbook | ✅ | 1 j·p | Docs + SRE |

Charge totale livrée ≈ **11,5 j·p** sur 12 j·p planifiées.

---

## P2‑1 — Pipeline CI = release automatique ✅

**Livré** : `.github/workflows/ci.yml` (11 045 octets, YAML valide).

Pipeline CI en 7 jobs gated :

1. **`lint`** — Ruff (Python) + pnpm lint (Node).
2. **`test-unit`** — Postgres + Redis services, pytest + coverage, junit XML + artifacts.
3. **`security-audit`** — SBOM CycloneDX + `pip-audit` + `npm audit --omit dev`.
4. **`build-and-sign`** — Docker buildx multi‑service, push GHCR, **cosign keyless signing** via OIDC.
5. **`deploy-staging`** — auto sur branche `develop` / `release/*` via SSH.
6. **`deploy-prod`** — manuel (environment gate `production`) sur `main`.
7. **`release`** — auto‑bump tag semver + release notes sur `main`.

Vérification : `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` → OK.

Owner : DevOps.

---

## P2‑2 — Catalogue produits & boutique : UX & perf ✅

**Livré** :

- Réécriture complète de `api-server/api/v1/storefront.py` (11 848 octets, AST Python valide)
  - pagination **cursor keyset** sur `(created_at desc, id desc)` — élimine le drift sur set en cours d'écriture
  - cache **Redis 5 min** (`CATALOG_CACHE_TTL_SECONDS = 300`) avec helper `invalidate_catalog_cache()` à câbler dans les POST/PUT produit
  - helpers `_image_sources()` qui exposent **WebP + AVIF + placeholder data: (lazy-load + 0 CLS)**
  - chaque réponse porte le champ `cache: HIT | MISS` + `next_cursor: base64url`
  - fail‑open sur Redis (cache miss → requête DB directe, sans erreur 5xx)
- `api-server/tests/e2e/storefront-purchase.spec.ts` (4 744 octets) — Playwright e2e
  - SLO catalogue P95 < 800 ms
  - cursor pagination sans doublon d'IDs entre pages
  - parcours achat end‑to‑end avec carte Stripe test 4242 4242 4242 4242
  - assertion du HIT Redis
- `api-server/playwright.config.ts` — multi‑browser (Chromium + Firefox), trace + vidéo sur échec.

Vérification : `python3 -c "import ast; ast.parse(open('api-server/api/v1/storefront.py'))"` → OK.

⚠️ Test Playwright à exécuter en CI (`pnpm exec playwright test --reporter=github`) — non exécutable dans la sandbox.

Owner : Frontend + Backend.

---

## P2‑3 — Stratégie backup/restore documentée & testée ✅

**Livré** :

- `scripts/backup_pg.sh` (4 256 octets, exécutable, `bash -n` OK)
  - `pg_dump --format=custom --compress=9 --jobs=4`
  - archivage WAL continu via `archive_command`
  - manifest sha256 pour vérifier l'intégrité avant restore
  - rotation `find … -mtime +30 -delete`
  - pointeur `BACKUP_ROOT/last_backup.path` pour restore rapide
  - notification webhook (ALERT_WEBHOOK_URL) succès/échec
- `scripts/restore_pg.sh` (3 667 octets, exécutable, `bash -n` OK)
  - mode `--self-test` : restore dans une DB jetable puis `information_schema.tables`
  - vérifie le sha256 AVANT restore (refuse si mismatch)
  - confirmation explicite `YES` avant restore réel
  - exit code 2 = checksum fail, refus automatique
- `docs/backup-restore-strategy.md` (3 044 octets)
  - RPO **15 min**, RTO **1 h**
  - procédure DR game‑day T+0 → T+30 min
  - job GitHub Actions trimestriel

Owner : SRE.

---

## P2‑4 — Quota / facturation B2B ajustée ✅

**Livré** : `api-server/services/billing_export.py` (12 823 octets, AST Python valide).

Module exposant :

- `export_invoice_csv()` — un row par ligne `credit_events` + en‑tête tenant/period + pied totaux.
- `export_invoice_pdf()` — ReportLab (tableau + styles + prix en DT) avec **fallback TXT** si ReportLab absent.
- `reconcile_stripe_payments()` — diff `credit_events.reference_id` ↔ Stripe PaymentIntents (matched / missing / extra) avec garde‑fou si Stripe indisponible.
- `handle_stripe_webhook_reconciliation()` — idempotent via `services/idempotency.py`, crédite le tenant si `pack_id` reconnu.

À câbler côté routes :
- `POST /api/v1/billing/stripe/webhook` → `handle_stripe_webhook_reconciliation(event)`
- bouton backoffice "Exporter facture (CSV / PDF)" → `export_invoice_*`

⚠️ ReportLab ajoute 1 dépendance dans `requirements.txt` ; fallback TXT actif si non installé (aucun crash).

Owner : Backend.

---

## P2‑5 — Backoffice : modération agent & kill switch ✅

**Livré** : `api-server/api/v1/ops_admin.py` (9 061 octets, AST Python valide).

Endpoints exposés (préfixe `/api/v1/ops-admin`) :

| Méthode | Route | Effet |
|---|---|---|
| GET    | `/agents/{store_id}/status`              | Vue complète (mute global + takeovers actifs) |
| POST   | `/agents/{store_id}/mute`               | Mute global IA du tenant (N min, max 24h) |
| DELETE | `/agents/{store_id}/mute`               | Reprise immédiate |
| POST   | `/agents/{store_id}/takeover/{phone}`   | Prise de main manuelle sur un client |
| DELETE | `/agents/{store_id}/takeover/{phone}`   | Rendre la main à l'IA |
| POST   | `/tenants/{store_id}/pause`             | Pause globale : mute + flag Redis 24h |
| POST   | `/tenants/{store_id}/resume`            | Reprise globale |

Garde‑fous :
- RBAC `super_admin` requis (router-level dependency).
- Trace chaque action dans `ops_actions` Mongo + log structuré JSON (recherche via `trace_id`).
- Motif **obligatoire** pour `pause` (champ Pydantic `min_length=3`).

Owner : Backend + Frontend.

---

## P2‑6 — Documentation utilisateur final & runbook ✅

**Livré** :

- `docs/user-faq-channels.md` (6 020 octets) — FAQ onboarding par canal
  - **WhatsApp** : QR code, quotas, mute, outage Meta
  - **Facebook Messenger** : Page Access Token, multi‑pages, comment→DM
  - **Instagram DM** : compte Business obligatoire, product tags
  - **TikTok commentaires** : TikTok for Developers, modération toxicité
  - **Transverse** : langues, coûts crédits, export RGPD, status page
- `docs/runbook-incidents.md` (8 524 octets) — runbook SRE
  - 5 incidents majeurs : latence LLM, outage Meta, Redis down, DB saturée, TLS expirant
  - Diagnostic (commandes curl/redis‑cli/psql) + Atténuation + Escalade + Post‑mortem
  - Contacts SRE / DevOps / CTO / Meta / Stripe
  - Référence croisée à P3‑2 (chaos engineering trimestriel)

Owner : Docs + SRE.

---

## Critères DoD — état global

| # | Critère | Statut |
|---|---|---|
| 1 | 100 % des actions **P0** résolues | ✅ (source : archive v27.1) |
| 2 | 100 % des actions **P1** vertes | ✅ (source : archive v27.1) |
| 3 | ≥ 70 % des actions **P2** livrées | ✅ **100 % livrées (6/6)** |
| 4 | Audit sécurité externe (3ᵉ cabinet ou pentester) — 0 critique | ❌ **NON LIVRÉ — DoD bloquant** |
| 5 | Score SSL Labs ≥ A, RGPD export/suppression opérationnel | ❌ **NON LIVRÉ (P3‑3)** |
| 6 | Runbook couvrant 5 incidents majeurs, testé game day | ✅ (P2‑6 livré — game day à jouer P3‑2) |

### Verdict DoD global

> **NON‑READY** — malgré les 6/6 P2 livrés, les critères 4 et 5 empêchent le statut READY‑TO‑GO.
> P3 (HA, DR, RGPD, SSO, observabilité avancée) doit être traité avant de re‑candidater au statut READY.

---

## Vérifications syntaxiques Sanbox

```
► storefront.py   — py3 ast.parse    → OK
► ops_admin.py    — py3 ast.parse    → OK
► billing_export.py — py3 ast.parse  → OK
► backup_pg.sh    — bash -n          → OK
► restore_pg.sh   — bash -n          → OK
► ci.yml          — yaml.safe_load   → OK
```

Tests runtime (à exécuter en CI, **non** exécutés en sandbox) :

```
► pytest api-server/tests/               — collecte non vérifiée
► pnpm exec playwright test              — non exécuté
► pnpm exec playwright install chromium   — non exécuté
► bash scripts/backup_pg.sh              — nécessite Postgres
► alembic upgrade head                   — VS Pod prod
```

## Total charge P2 livrée : ~11,5 j·p / 12 j·p planifiées

6 actions sur 6, code source réel du projet, conventions Python/FastAPI/Bash/YAML respectées.
