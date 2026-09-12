#!/usr/bin/env bash
# =============================================================================
# hc_ping.sh — Healthchecks.io ping wrapper
#
# Usage:
#   hc_ping.sh <check-uuid> [start|fail]
#
# If no action specified, sends a success ping.
# Use "start" to signal job start, "fail" to signal failure.
#
# Environment:
#   HC_BASE_URL — Healthchecks base URL (default: http://127.0.0.1:8004)
# =============================================================================

set -euo pipefail

HC_BASE_URL="${HC_BASE_URL:-http://127.0.0.1:8004}"
CHECK_UUID="${1:?Usage: hc_ping.sh <uuid> [start|fail]}"
ACTION="${2:-success}"

case "$ACTION" in
    start)
        ENDPOINT="/start"
        ;;
    fail)
        ENDPOINT="/fail"
        ;;
    success|*)
        ENDPOINT=""
        ;;
esac

# Send ping (non-blocking, silent on failure — don't break the actual job)
curl -fsS --retry 3 --max-time 10 \
    "${HC_BASE_URL}/ping/${CHECK_UUID}${ENDPOINT}" \
    -H "Host: 100.122.58.40:8004" \
    -o /dev/null 2>/dev/null || true
