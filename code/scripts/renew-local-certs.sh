#!/bin/bash
# renew-local-certs.sh — Regenerate local CA and wildcard *.home cert
# Called annually via cron. Also recreates nginx custom cert entry.

set -euo pipefail

CA_DIR="/data/custom_ssl/local-ca"
WILD_DIR="/data/custom_ssl/wildcard-home"
NPM_CONTAINER="nginx-proxy-manager"
LOG="/home/rohit/.hermes/logs/renew_local_certs.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "Starting local cert renewal..."

# Check if cert expires within 90 days
EXPIRY=$(docker exec "$NPM_CONTAINER" openssl x509 \
  -in "$WILD_DIR/wildcard.home.crt" -noout -enddate 2>/dev/null | cut -d= -f2)
EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s 2>/dev/null || echo 0)
NOW_EPOCH=$(date +%s)
DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))

if [ "$DAYS_LEFT" -gt 90 ]; then
  log "Cert still valid for $DAYS_LEFT days. Skipping renewal."
  exit 0
fi

log "Cert expires in $DAYS_LEFT days. Renewing..."

# Regenerate wildcard cert (CA is still valid, just renew the leaf)
docker exec "$NPM_CONTAINER" bash -c "
  openssl genrsa -out '$WILD_DIR/wildcard.home.key' 2048 2>&1

  openssl req -new -key '$WILD_DIR/wildcard.home.key' \
    -out '$WILD_DIR/wildcard.home.csr' \
    -subj '/C=US/ST=Home/L=Home/O=Homelab/CN=*.home'

  cat > /tmp/wildcard_ext.cnf << EXTEOF
subjectAltName=DNS:*.home,DNS:home
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
EXTEOF

  openssl x509 -req -days 3650 \
    -in '$WILD_DIR/wildcard.home.csr' \
    -CA '$CA_DIR/ca.crt' \
    -CAkey '$CA_DIR/ca.key' \
    -CAcreateserial \
    -out '$WILD_DIR/wildcard.home.crt' \
    -extfile /tmp/wildcard_ext.cnf
"

# Reload nginx to pick up new cert
docker exec "$NPM_CONTAINER" nginx -s reload 2>/dev/null

log "Local cert renewed successfully. New expiry: $(docker exec "$NPM_CONTAINER" openssl x509 -in "$WILD_DIR/wildcard.home.crt" -noout -enddate | cut -d= -f2)"
