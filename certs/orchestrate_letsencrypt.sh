#!/usr/bin/env bash
set -euo pipefail
DOMAIN="${1:-autocommerce.example.com}"
EMAIL="${LETSENCRYPT_EMAIL:-admin@example.com}"
certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" --agree-tos -m "$EMAIL" --non-interactive ${2:-}
nginx -s reload
