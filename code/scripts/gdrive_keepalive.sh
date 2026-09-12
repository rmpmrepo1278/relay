#!/bin/bash
# gdrive_keepalive.sh — Keep GDrive OAuth token alive and alert if re-auth needed
# Runs every 6 hours via cron
# ponytail: single script, no classes, just check+alert with specific diagnosis

LOG="/home/rohit/.hermes/logs/gdrive_keepalive.log"
mkdir -p "$(dirname "$LOG")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

# Quick health check — a successful rclone about proves token is alive
if rclone about gdrive: >> /dev/null 2>&1; then
    log "OK: gdrive responsive"
    exit 0
fi

# Diagnose the failure
ERROR=$(rclone about gdrive: 2>&1)
log "ERROR: $ERROR"

# invalid_grant = refresh token itself is dead (expired or revoked)
# Network errors are transient — no alert needed, just log
if echo "$ERROR" | grep -q "invalid_grant"; then
    MSG="🔴 GDrive OAuth token REVOKED (invalid_grant). Refresh token is dead — needs full re-auth.

Run on server (prints a URL to open in any browser):
  rclone config reconnect gdrive: --auto-confirm

Or with SSH port-forward from your laptop:
  ssh -L 53682:localhost:53682 rohit@192.168.29.10
  rclone config reconnect gdrive: --auto-confirm

FIX ROOT CAUSE: Publish OAuth app to Production in Google Cloud Console → OAuth Consent Screen → PUBLISH APP. Testing-mode tokens expire every 7 days."
    log "ALERT: invalid_grant — refresh token dead, manual re-auth needed"
elif echo "$ERROR" | grep -q "i/o timeout\|lookup\|network\|connection refused"; then
    # Network/DNS issue — transient, don't alert
    log "WARN: network error, likely transient — skipping alert"
    exit 1
else
    # Unknown error — alert with raw message
    MSG="🟡 GDrive keepalive failed: $(echo "$ERROR" | tail -1)"
    log "ALERT: unknown error"
fi

# Send alert — try gateway API first (more reliable), fall back to hermes CLI
if curl -sf -X POST http://localhost:8787/api/send \
    -H "Content-Type: application/json" \
    -d "{\"message\": $(printf '%s' "$MSG" | jq -Rs .)}" >> /dev/null 2>&1; then
    log "Alert sent via gateway API"
elif command -v hermes >> /dev/null 2>&1; then
    hermes send -t telegram "$MSG" 2>> "$LOG"
    log "Alert sent via hermes CLI"
else
    log "ALERT: Could not send notification (no gateway or CLI available)"
fi

exit 1
