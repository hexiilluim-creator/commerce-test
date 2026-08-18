#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$(dirname "$0")/live"
openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "$(dirname "$0")/live/privkey.pem" \
  -out "$(dirname "$0")/live/fullchain.pem" \
  -days 365 \
  -subj "/CN=localhost"
cp "$(dirname "$0")/live/fullchain.pem" "$(dirname "$0")/client_ca.pem"
echo "Certificats de développement générés dans certs/live/"
