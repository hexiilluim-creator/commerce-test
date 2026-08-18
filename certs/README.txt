Certificats de production attendus:
  certs/live/fullchain.pem
  certs/live/privkey.pem
  certs/client_ca.pem   (optionnel si mTLS activé sur /api/v1/agent/*)

Provisioning recommandé:
  CERTBOT_EMAIL=ops@example.com CERTBOT_DOMAIN=api.example.com bash scripts/renew_tls_certs.sh
