# release-evidence/ — état V28

**Mise à jour : `release-evidence/v28.1.3/` a été généré et est disponible**
(scan de secrets + revue manuelle, pip_audit, npm_audit + correctif appliqué,
build frontend réel, suite pytest complète hors tests nécessitant Postgres).
Voir `v28.1.3/VALIDATION_SUMMARY.md` pour le détail complet et les limites
honnêtement documentées (tests/security/ et tests/integration/ nécessitent
un vrai Postgres, non disponible dans le sandbox qui a généré ce dossier —
dernière exécution réelle confirmée par un tiers en environnement de
déploiement réel, voir CHANGES_V28.md P1.4-P1.8).

`v27.1.0/` reste conservé ci-dessous comme historique de la release
précédente.

---

## Historique (avant génération de v28.1.3/)

Le seul dossier de preuves runtime présent dans cette archive est
`v27.1.0/` (smoke tests, audit secrets, SBOM, pip/npm audit — datés de
la release V27.1).

**Aucune preuve runtime équivalente n'existe encore pour V28.** Le VERSION
du package a été avancé à 28.0.0, mais générer un nouveau
`release-evidence/v28.0.0/` (smoke P0/P1, audit secrets, SBOM, pip/npm audit)
n'a pas été fait ici — je ne fabrique pas de résultats de test que je n'ai
pas réellement exécutés contre un environnement de staging.

C'est l'action #5 recommandée par l'audit CTO : produire une preuve runtime
V28 réelle (staging PostgreSQL/Redis, smoke end-to-end, test cross-tenant,
upload, worker Celery, intégrations annoncées) avant un GO production.
Tant que `release-evidence/v28.0.0/` n'existe pas, considérer la
"validation" de ce package comme non prouvée en exécution.

