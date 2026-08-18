---
severity: critical
owner: SRE Team
MTTD: 15m
MTTR: 45m
---

# Runbook: Storage S3/MinIO Down

## Symptômes

- Erreurs `S3ConnectionError` ou `MinIOConnectionError` dans les logs.
- Impossible de télécharger ou d'uploader des fichiers (images, documents).
- Fonctionnalités de l'application affectées (ex: images produits manquantes).

## Cause probable

- Le service S3 (AWS) ou MinIO est indisponible.
- Problème de connectivité réseau.
- Problème d'authentification (clés API).

## Étapes diagnostic

1. **Vérifier les logs:** `kubectl logs -f <api-server-pod> | grep S3ConnectionError`
2. **Vérifier le statut du service:** Consulter la console AWS S3 ou le statut du pod MinIO (`kubectl get pods -l app=minio`).
3. **Tester la connectivité:** `aws s3 ls` (si AWS S3) ou `mc ls` (si MinIO) depuis un pod `api-server`.
4. **Vérifier les identifiants:** S'assurer que `AWS_ACCESS_KEY_ID` et `AWS_SECRET_ACCESS_KEY` sont corrects.

## Étapes mitigation

1. **Redémarrer le service MinIO:** Si MinIO est utilisé, `kubectl rollout restart deployment minio`.
2. **Vérifier la configuration réseau:** S'assurer que les règles de pare-feu n'ont pas changé.
3. **Mettre à jour les identifiants:** Si les clés API sont expirées ou incorrectes.

## Post-mortem template

- **Date et heure de l'incident:**
- **Durée:**
- **Services affectés:**
- **Cause racine:**
- **Actions correctives:**
- **Actions préventives:**

