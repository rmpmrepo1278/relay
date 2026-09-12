#!/bin/bash
# dns_healthcheck.sh — Check DNS resolution and auto-remediate if all upstreams fail.
# Outage-aware: during the known nightly outage window (11PM-9AM PT) DNS failures are
# expected — log them but skip remediation so the script stays green and fast.
set -euo pipefail

LOG_FILE="$HOME/.hermes/logs/dns_healthcheck.log"
TIMEOUT=3

# Known outage window? (mirrors mcp_health_watchdog). Set OUTAGE_SKIP.
GUARD_PY="$HOME/.hermes/scripts/lib/network_guard.py"
OUTAGE_SKIP=0
if [ -f "$GUARD_PY" ]; then
    # shell protocol: exit 0 = in outage/DNS flap -> skip remediation
    if python3 "$GUARD_PY" >/dev/null 2>&1; then
        OUTAGE_SKIP=1
    fi
fi

check_dns() {
    dig "@$1" "$2" +short +timeout="$TIMEOUT" +tries=1 2>/dev/null | head -1
}

G_RESULT=$(check_dns "8.8.8.8" "google.com")
C_RESULT=$(check_dns "1.1.1.1" "cloudflare.com")
Q_RESULT=$(check_dns "9.9.9.9" "quad9.net")
# WAN check via ping
ping -c 2 -W "$TIMEOUT" 8.8.8.8 >/dev/null 2>&1 && WAN_UP=1 || WAN_UP=0

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

if [ -z "$G_RESULT" ] && [ -z "$C_RESULT" ] && [ -z "$Q_RESULT" ]; then
    if [ "$WAN_UP" -eq 0 ]; then
        echo "[$TIMESTAMP] WAN down — all DNS unreachable" >> "$LOG_FILE"
    elif [ "$OUTAGE_SKIP" -eq 1 ]; then
        echo "[$TIMESTAMP] known outage window — skipping pihole restart" >> "$LOG_FILE"
    else
        echo "[$TIMESTAMP] CRITICAL: WAN up but all DNS failed — restarting pihole" >> "$LOG_FILE"
        timeout 8 docker restart pihole >/dev/null 2>&1 || true
    fi
elif [ -z "$G_RESULT" ]; then
    echo "[$TIMESTAMP] Google DNS unreachable" >> "$LOG_FILE"
fi
if [ -z "$C_RESULT" ]; then
    echo "[$TIMESTAMP] Cloudflare DNS unreachable" >> "$LOG_FILE"
fi
if [ -z "$Q_RESULT" ]; then
    echo "[$TIMESTAMP] Quad9 DNS unreachable" >> "$LOG_FILE"
fi

exit 0