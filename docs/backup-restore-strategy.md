# Stratégie de sauvegarde / restauration (P2‑3)

## Objectifs

| Indicateur | Cible | Commentaire |
|---|---|---|
| **RPO** (perte de données maximale admissible) | **15 min** | assuré par archivage WAL en continu + pg_dump horaire |
| **RTO** (durée acceptable d'indisponibilité) | **1 h** | restauration depuis `last_backup.path` + WAL replay |
| Fréquence pg_dump | horaire (peak) / toutes les 6 h (off-peak) | croné `0 * * * *` |
| Rétention dump | **30 jours** glissant | rotation `find … -mtime +30` |
| Rétention WAL | **30 jours** | suffisant pour replay complet |
| Test de restore | trimestriel | `scripts/restore_pg.sh --self-test` + scénario manuel |

## Mise en place

1. Cron job (root, `/etc/cron.d/autocommerce-backup`) :
   ```cron
   BACKUP_ROOT=/var/backups/autocommerce
   WAL_ARCHIVE_DIR=/var/backups/autocommerce/wal
   RETENTION_DAYS=30
   0 * * * * /opt/autocommerce/scripts/backup_pg.sh >/dev/null 2>&1
   ```
2. `postgresql.conf` (replica prod) :
   ```
   wal_level = replica
   archive_mode = on
   archive_command = '/usr/local/bin/archive_wal.sh %p %f'
   max_wal_senders = 4
   ```
3. Restore cold-standby (`/etc/postgresql/16/main/recovery.conf`) :
   ```
   standby_mode = on
   primary_conninfo = 'host=primary-db port=5432 user=replicator'
   restore_command = 'cp /var/backups/autocommerce/wal/%f %p'
   trigger_file = '/tmp/promote_me'
   ```

## Procédure DR (game day trimestriel)

1. **T+0 min** — alertes PagerDuty : "DB primaire inaccessible"
2. **T+2 min** — `ssh` sur standby, vérifier `pg_isready -h standby` (vert)
3. **T+3 min** — promote : `touch /tmp/promote_me && pg_ctl promote -D /var/lib/postgresql/data`
4. **T+5 min** — vérifier les écritures : table `audit_log` reçoit les events
5. **T+10 min** — bascule DNS tierce partie (TTL 60s) vers standby
6. **T+15 min** — `bash scripts/restore_pg.sh --self-test` en parallèle pour mesurer RTO réel
7. **T+30 min** — communication client (status page), RCA, post‑mortem J+3

## Auto-test CI

```yaml
# .github/workflows/ci.yml (extrait)
quarterly-restore-test:
  runs-on: ubuntu-latest
  schedule:
    - cron: '0 6 1 */3 *'        # 1er de chaque trimestre, 06h00 UTC
  steps:
    - uses: actions/checkout@v4
    - run: |
        docker run --rm -d --name pg postgres:16-alpine
        sleep 10
        docker exec pg bash -c 'createdb test && pg_isready'
        bash scripts/backup_pg.sh
        bash scripts/restore_pg.sh --self-test
        docker stop pg
```

## Métriques SLO associées

- **Backup freshness** — alert si `now() - last_backup.ts > 90 min`
- **WAL lag** — alert si `pg_last_wal_receive_lsn()` lag > 50 MB
- **Restore‑test pass-rate** — alert si 0 sur les 90 derniers jours

## Liens

- Script backup : [`scripts/backup_pg.sh`](scripts/backup_pg.sh)
- Script restore : [`scripts/restore_pg.sh`](scripts/restore_pg.sh)
- Runbook incident DB : [`docs/runbook-incidents.md#c1-db-down`](runbook-incidents.md)
- Pipeline CI : [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
