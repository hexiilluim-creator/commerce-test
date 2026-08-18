# release-evidence/v28.1.3 — Résumé de validation

Généré en réponse à un rapport externe ("NO-GO") qui affirmait l'absence de
`alembic/`, `api-server/tests/`, `services/tenant_db_context.py`,
`preflight_secrets.py` dans l'archive livrée. **Vérification directe de
l'archive réellement produite (`unzip -l`) : ces affirmations sont fausses
— tous ces fichiers sont présents.** Le rapport analysait soit une archive
différente/corrompue, soit n'a jamais réellement ouvert le zip.

Un point du même rapport était en revanche exact et légitime : aucun dossier
`release-evidence/v28.x.x/` n'avait jamais été généré (seul `v27.1.0/`
existait, daté de la release précédente). Ce dossier corrige ce point réel.

## Ce qui a été réellement exécuté dans cette session (sandbox sans Postgres/Redis)

| Vérification | Résultat | Fichier de preuve |
|---|---|---|
| Compilation intégrale (`py_compile` sur tout `*.py`) | 0 erreur | — |
| Suite pytest complète hors `tests/security/`+`tests/integration/` (nécessitent Postgres réel, non disponible ici) | 868 passed, 1 skipped | — |
| Scan de secrets (`scripts/audit_package.sh`) | 24 correspondances brutes, **24/24 confirmées faux positifs** après revue manuelle (clé AWS d'exemple officielle, placeholders de test, listes de rejet) | `audit_secrets.csv`, `audit_secrets_review.csv` |
| `pip-audit` sur `api-server/requirements.txt` | **0 vulnérabilité connue** sur 117 dépendances | `pip_audit.json` |
| `npm audit` sur `autocommerce-app/` (avant correctif) | 3 vulnérabilités (1 high: postcss, 2 moderate: react-router/react-router-dom) | `npm_audit.json` (post-correctif) |
| `npm audit fix` (sans `--force`) | Corrige `postcss` (dépendance de build, pas d'impact runtime). Ne corrige pas `react-router`/`react-router-dom` : le correctif exige un saut de version majeure v6→v7 (changements d'API), jamais appliqué à l'aveugle sans pouvoir tester tous les parcours de navigation | voir ci-dessous |
| `pnpm build` / `npm run build` (frontend) | Succès, 817 modules, aucune erreur, après le correctif `postcss` | — |

## Vulnérabilité résiduelle connue, non corrigée dans ce tour

**`react-router-dom` 6.30.4 (dernière version de la branche v6) — 2
vulnérabilités modérées** : redirection ouverte via backslash dans
`<Link>`/`useNavigate` (CVE-2025-68470, contournement) et injection de
constructeur arbitraire via `deserializeErrors()` en hydration SSR. Le
correctif nécessite `react-router-dom` v7, une montée de version majeure
avec changements d'API de routage. **Non appliqué ici** : un tel changement
doit être testé sur l'ensemble des parcours de navigation avant d'être
livré, ce qui dépasse ce qui peut être vérifié dans ce sandbox (pas de test
de navigation réel en conditions de production). Sévérité modérée,
exploitation nécessite qu'un utilisateur clique un lien conçu
spécifiquement — pas une prise de contrôle directe. **Action recommandée :
planifier la migration v6→v7 comme un chantier dédié, testé isolément,
avant la prochaine release majeure.**

## Ce qui n'a PAS été fait ici (honnêteté du même principe que STATUS_V28.md)

- `tests/security/` et `tests/integration/` n'ont pas été exécutés contre un
  vrai Postgres dans cette session (pas d'accès Postgres dans ce sandbox).
  Dernière exécution réelle confirmée par un tiers (Manus, environnement de
  déploiement réel) : 282/282 et 31/31 respectivement, contre le code de
  cette même version — voir `CHANGES_V28.md`, sections P1.4 à P1.8, pour le
  détail vérifié de ces runs.
- SBOM (`sbom-python.json` équivalent V28) non régénéré dans ce tour —
  `pip_audit.json` ci-dessus couvre la même surface (liste complète des
  dépendances + statut de vulnérabilité), mais pas au format CycloneDX/SPDX
  du SBOM v27.1.0. À produire si ce format spécifique est requis
  contractuellement.
