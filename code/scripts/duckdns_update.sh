#!/bin/bash
# DuckDNS Update Script
# Updates chagulihome.duckdns.org to current public IP
# Token must be set in DUCKDNS_TOKEN env var or ~/.duckdns_token file

set -euo pipefail

# Outage-aware guard: skip silently during known nightly outage window or DNS flap
GUARD_PY="$HOME/.hermes/scripts/lib/network_guard.py"
if [ -f "$GUARD_PY" ]; then
    if python3 "$GUARD_PY" >/dev/null 2>&1; then
        echo "[$(date '+%F %T')] skipped (outage/dns-guard)" | logger -t duckdns_update 2>/dev/null || true
        exit 0
    fi
fi

DOMAIN="chagulihome"
TOKEN_FILE="$HOME/.duckdns_token"

# Get token from env or file
if [ -z "${DUCKDNS_TOKEN:-}" ]; then
    if [ -f "$TOKEN_FILE" ]; then
        DUCKDNS_TOKEN=$(cat "$TOKEN_FILE")
    else
        echo "ERROR: DuckDNS token not found. Set DUCKDNS_TOKEN env var or create $TOKEN_FILE"
        exit 1
    fi
fi

# Check for placeholder token
if [ "$DUCKDNS_TOKEN" = "PASTE_YOUR_TOKEN_HERE" ] || [ -z "$DUCKDNS_TOKEN" ]; then
    echo "ERROR: DuckDNS token not configured. Get your token from https://www.duckdns.org/account"
    echo "Then run: echo 'YOUR_TOKEN' > ~/.duckdns_token && chmod 600 ~/.duckdns_token"
    exit 1
fi

# Get current public IP
CURRENT_IP=$(curl -s --max-time 10 https://api.ipify.org 2>/dev/null)
if [ -z "$CURRENT_IP" ]; then
    echo "ERROR: Could not determine current public IP"
    exit 1
fi

# Get current DNS record
DNS_IP=$(dig +short "${DOMAIN}.duckdns.org" @8.8.8.8 2>/dev/null | head -1)

if [ "$CURRENT_IP" = "$DNS_IP" ]; then
    echo "OK: DNS already up-to-date ($CURRENT_IP)"
    echo "OK: DNS already up-to-date ($CURRENT_IP)" | logger -t duckdns_update 2>/dev/null || true
    exit 0
fi

echo "Updating DuckDNS: $DNS_IP -> $CURRENT_IP"

# Update DuckDNS
RESULT=$(curl -s --max-time 10 "https://www.duckdns.org/update?domains=${DOMAIN}&token=${DUCKDNS_TOKEN}&ip=${CURRENT_IP}" 2>/dev/null)

if [ "$RESULT" = "OK" ]; then
    echo "SUCCESS: DuckDNS updated to $CURRENT_IP"
    echo "SUCCESS: DuckDNS updated to $CURRENT_IP" | logger -t duckdns_update 2>/dev/null || true
    # Verify
    sleep 5
    NEW_DNS_IP=$(dig +short "${DOMAIN}.duckdns.org" @8.8.8.8 2>/dev/null | head -1)
    if [ "$NEW_DNS_IP" = "$CURRENT_IP" ]; then
        echo "VERIFIED: DNS now resolves to $NEW_DNS_IP"
    else
        echo "WARN: DNS still shows $NEW_DNS_IP (propagation may take time)"
    fi
else
    echo "ERROR: DuckDNS update failed (response: $RESULT)"
    echo "ERROR: DuckDNS update failed (response: $RESULT)" | logger -t duckdns_update 2>/dev/null || true
    exit 1
fi
