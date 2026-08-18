# P1 Observability Runbook

## Dashboards
- Grafana dashboard: `monitoring/grafana/autocommerce_llm_observability_dashboard.json`
- Prometheus rules: `monitoring/prometheus/alert_rules.yml`

## Core SLOs
- p95 agent latency < 2 seconds over 5 minutes
- webhook error rate (5xx + 429) < 1%
- queue backlog cleared in < 10 minutes
- daily LLM cost stays under tenant budget

## Synthetic blackbox probes
- `GET /api/health/live` every 60s
- `GET /api/health/ready` every 60s
- External HTTPS probe on public Omnical ingress every 60s

## TLS operations
- run `scripts/renew_tls_certs.sh`
- alert at J-30 and J-7 before certificate expiry
