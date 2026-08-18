# Runbook incidents — AutoCommerce Enterprise V27.2 (P2‑6)

> Cible : SRE, DevOps, support L2/L3.
> 5 incidents majeurs connus — chacun comporte diagnostic, atténuation, escalade, post‑mortem.
> À tester en **game day** trimestriel (cf. P3‑2).

## Légende sévérité

| Sev | Définition | Délai avant action |
|---|---|---|
| **SEV-1** | Service down ou perte de données | < 5 min |
| **SEV-2** | Dégradation majeure (>25% erreurs / latence p95 ×3) | < 30 min |
| **SEV-3** | Dégradation mineure | < 4 h ouvrées |
| **SEV-4** | Anomalie non bloquante | sous 24 h |

---

## Incident #1 — Latence LLM (p95 > 5 s)

### Symptômes
- Métriques `_autocomplete_llm_latency_seconds{...}` P95 > 5 s (alerte Prometheus)
- Conversations qui « moulinent » > 10 s avant réponse
- Tickets clients « le bot met 30 secondes à répondre »

### Diagnostic
```bash
# 1. Vérifier la santé du provider LLM principal
curl -fsS https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY" | jq '.data[].id' | head -3

# 2. Vérifier le débit tokens/min
curl -fsS http://prometheus:9090/api/v1/query \
  --data-urlencode 'query=sum by (model) (rate(_autocommerce_prompt_tokens_total[5m]))'

# 3. Vérifier fallback (Mistral ou stub local)
curl -fsS http://prometheus:9090/api/v1/query \
  --data-urlencode 'query=sum by (model,status) (rate(_autocomplete_llm_latency_seconds_count[5m]))'
```

### Atténuation
1. **Bascule automatique** vers le LLM secondaire (Mistral) si configurée :
   `kubectl set env deployment/api-server OPENAI_FALLBACK_ENABLED=true`
2. **Si tous les providers sont HS** → fallback sur `services/llm_stub.py` (réponses pré‑enregistrées) :
   - Cohérent mais limité : informer les clients via status page
3. **Rate-limit bas** sur les routes `/agent/*` (30/min/user) pour absorber la queue

### Escalade
- SEV-2 → notifier `#incident-bot`, on-call SRE
- SEV-1 si > 30 min → escalation management
- Page status publique : https://status.autocommerce.example

### Post‑mortem
- Vérifier quotas OpenAI/Mistral
- Optimiser cache prompt (semantic cache si > 25% de questions répétées)
- Réviser alert thresholds P95

---

## Incident #2 — Outage Meta (WhatsApp / Messenger / IG)

### Symptômes
- Métriques omnicall_v9 returns 5xx ou timeout
- Webhooks Meta retournent 5xx dans `/metrics`
- Health check `/health/ready` rouge sur service `meta-bridge`

### Diagnostic
```bash
# 1. Tester directement les endpoints Meta
curl -fsS https://graph.facebook.com/v18.0/me -H "Authorization: Bearer $META_ACCESS_TOKEN" | head -20

# 2. Vérifier le circuit breaker omnicall
curl -fsS http://prometheus:9090/api/v1/query \
  --data-urlencode 'query=omnicall_circuit_breaker_state'

# 3. Vérifier la file d'attente
redis-cli -u $REDIS_URL LLEN omnicall:queue:incoming
```

### Atténuation
1. **Circuit breaker** se déclenche automatiquement après 5 échecs consécutifs (cf. `omnicall_v9/circuit_breaker.py`)
2. **Requeue automatique** : tous les messages non délivrés restent en Redis (`omnicall:queue:incoming`) et sont rejoués dès la reprise
3. **Communication client** : status page + email automatique aux marchands Premium
4. **Si outage > 1 h** : proposer prise en charge manuelle via console admin

### Escalade
- SEV-1 → Bridger Meta : `eng@autocommerce.example`
- Page status publique
- Weekly review avec Meta si récurrence

### Post‑mortem
- Vérifier si le circuit breaker s'est ouvert correctement
- Logs `omnicall_v9/observability/events.py` à analyser
- Demande post-mortem à Meta si > 4 h d'outage

---

## Incident #3 — Redis indisponible

### Symptômes
- Health check rouge sur service Redis
- Erreurs 503 sur `/api/v1/*` (cache fall-through lent)
- `services/agent_mute.py` lève « Redis unavailable »

### Diagnostic
```bash
# 1. Tester redis
redis-cli -u $REDIS_URL ping   # PONG attendu

# 2. Vérifier la mémoire
redis-cli -u $REDIS_URL info memory | grep -E "used_memory_human|maxmemory_human"

# 3. Voir les clients connectés
redis-cli -u $REDIS_URL info clients
```

### Atténuation
1. **Bascule Redis Sentinel** automatique (cf. `docker-compose.ha.yml`)
2. **Fail-open** sur les lecteurs Redis :
   - `services/agent_mute.py` : l'IA reste active (mieux que bloquer tout)
   - Cache catalogue : MISS systématique (latence accrue, mais service rendu)
3. **Si Redis totalement down** : restart propre + chargement des snapshots récents

### Escalade
- SEV-2 → SRE on-call
- Si extends > 30 min pendant business hours → SEV-1

### Post‑mortem
- Capacity planning : augmenter RAM si OOM
- Tuner `maxmemory-policy=allkeys-lru` si évictions excessives
- Snapshotting RDS si coût IO élevé

---

## Incident #4 — DB PostgreSQL saturée (connexions / CPU / disque)

### Symptômes
- Alerte `pg_stat_activity_count > 80%` du `max_connections`
- Requêtes `SELECT * FROM orders` timeout 30 s
- `df -h /var/lib/postgresql` > 90%

### Diagnostic
```bash
# 1. Connexions actives
psql -U autocommerce -c "SELECT count(*), state, application_name FROM pg_stat_activity GROUP BY state, application_name ORDER BY 1 DESC;"

# 2. Long-running queries
psql -U autocommerce -c "SELECT pid, now()-query_start as age, state, query FROM pg_stat_activity WHERE state='active' ORDER BY age DESC LIMIT 10;"

# 3. Espace disque
df -h /var/lib/postgresql/data
du -sh /var/lib/postgresql/data/* | sort -h
```

### Atténuation
1. **Kill connexions idle-in-transaction > 5 min** :
   `psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state='idle in transaction' AND query_start < now() - interval '5 min';"`
2. **PgBouncer** : si saturé, basculer sur `pool_mode=transaction` (déjà par défaut)
3. **Nettoyage table `audit_log`** : archiver > 90 jours dans S3 froid + `VACUUM FULL`
4. **Si CPU saturé** : kill requêtes lentes + activer `pg_stat_statements` pour profiling

### Escalade
- SEV-1 imminent → bascule vers standby (cf. [`backup-restore-strategy.md`](backup-restore-strategy.md))
- Communication client si > 30 min

### Post‑mortem
- Identifier la requête N+1 (souvent storefront ou tableau de bord)
- Ajouter index si manquant (cf. `alembic/versions/0021_composite_indexes_1k_tenants.py`)
- Revoir la pagination storefront (cf. P2‑2 cursor)

---

## Incident #5 — Certificat TLS expirant (J‑7 / J‑0)

### Symptômes
- Alerte `tls_cert_expiry_days < 7` (Prometheus)
- Erreurs navigateur `NET::ERR_CERT_DATE_INVALID`
- Page status rouge avec mention « TLS »

### Diagnostic
```bash
# 1. Date d'expiration
echo | openssl s_client -connect autocommerce.example:443 -servername autocommerce.example 2>/dev/null | openssl x509 -noout -dates

# 2. Test ssllabs (référence externe)
# https://www.ssllabs.com/ssltest/analyze.html?d=autocommerce.example

# 3. Vérifier la chaîne
curl -vI https://autocommerce.example 2>&1 | grep -E "subject|issuer"
```

### Atténuation
1. **Renouvellement ACME** automatique (`scripts/renew_tls_certs.sh`) :
   ```bash
   bash /opt/autocommerce/scripts/renew_tls_certs.sh
   systemctl reload nginx
   ```
2. **Si échec ACME** : renouvellement manuel via DigiCert / Let's Encrypt
3. **Si J-0** : utiliser certificat backup pré‑généré (staging) + plan B = HSTS bypass navigateur pour test uniquement

### Escalade
- SEV-2 → SRE on-call + DevOps
- Status page publique

### Post‑mortem
- Mettre en place monitoring cert expiry J-60 / J-30 / J-15 / J-7 / J-1
- Documenter le runbook ACME et le tester game day

---

## Annexes

### Contacts

| Rôle | Contact | Délai |
|---|---|---|
| SRE on-call | pagerDuty AutoCommerce | < 5 min |
| DevOps lead | devops@autocommerce.example | < 30 min |
| CTO | cto@autocommerce.example | < 2 h |
| Meta engineering | via reproteur partenaire | < 4 h |
| Stripe support | dashboard.stripe.com → help | < 24 h |

### Liens utiles

- Status page : https://status.autocommerce.example
- Dashboard Grafana : https://grafana.autocommerce.example (équipe only)
- Runbook CI : [`backup-restore-strategy.md`](backup-restore-strategy.md)
- Pipeline CI : [`../.github/workflows/ci.yml`](../.github/workflows/ci.yml)
- Métriques Prometheus : [`../monitoring/prometheus/alert_rules.yml`](../monitoring/prometheus/alert_rules.yml)

### Tests game day trimestriels

Cf. P3‑2 — chaque incident ci-dessus doit être rejoué au moins 1× par trimestre, avec :
- injection du défaut simulé (chaos-mesh / toxiproxy)
- timer le RTO effectivement obtenu
- rédaction du compte-rendu post-mortem (même pour un succès)
