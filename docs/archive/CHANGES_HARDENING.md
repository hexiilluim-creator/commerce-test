# Hardening et corrections de livraison V25

## Correctifs appliqués sur ce package
1. **Preflight assaini**
   - plus de faux positif : le script ne termine plus en succès tant que le round-trip manuel n’a pas été explicitement validé.
   - ajout d’un contrôle de présence des documents de release.
   - ajout de l’audit de package dans le preflight.

2. **Références documentaires restaurées**
   - restauration de `docs/deployment-strategy.md` et des documents de handover/governance manquants.

3. **Package nettoyé**
   - suppression des artefacts générés (`.coverage`, `.tsbuildinfo`, `dist/`, `__pycache__/`).

4. **Traçabilité de release améliorée**
   - guides explicites pour monitoring, portail B2B, architecture Plan F/G, onboarding et go/no-go final.

## Contrôles recommandés avant diffusion
- audit de package
- tests sécurité ciblés
- build frontend
- audit dépendances
- validation manuelle du round-trip entreprise
