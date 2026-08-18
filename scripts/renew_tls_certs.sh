#!/usr/bin/env bash
set -euo pipefail

CERTBOT_EMAIL="${CERTBOT_EMAIL:-ops@example.com}"
CERTBOT_DOMAIN="${CERTBOT_DOMAIN:-api.example.com}"
WEBROOT="${WEBROOT:-/var/www/certbot}"
CERT_DIR="${CERT_DIR:-./certs/live}"

mkdir -p "$WEBROOT" "$CERT_DIR"
certbot certonly --non-interactive --agree-tos --webroot -w "$WEBROOT"       -m "$CERTBOT_EMAIL" -d "$CERTBOT_DOMAIN"

cp "/etc/letsencrypt/live/$CERTBOT_DOMAIN/fullchain.pem" "$CERT_DIR/fullchain.pem"
cp "/etc/letsencrypt/live/$CERTBOT_DOMAIN/privkey.pem" "$CERT_DIR/privkey.pem"
chmod 600 "$CERT_DIR/privkey.pem"
echo "[tls] certificat renouvelé pour $CERTBOT_DOMAIN"
