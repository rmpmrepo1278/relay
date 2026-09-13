#!/bin/bash
# cve_scan.sh - weekly trivy scan of key images. Report-only (exit 0) so the
# scheduler job never false-fails; results logged for review.
# Sep 13 2026: added SUMMARY lines (the tail -20 cut the Total: line that sits
# above the table, leaving per-image totals unrecoverable from the log).
set -uo pipefail
LOG=/home/rohit/.hermes/logs/cve_scan.log
IMAGES=$(docker ps --format "{{.Image}}" | grep -E "hermes-agent|immich|paperless|traefik" | sort -u)
if [ -z "$IMAGES" ]; then
  echo "[$(date -Iseconds)] WARN: no matching images found" >> "$LOG"
  exit 0
fi
echo "[$(date -Iseconds)] cve_scan start: $IMAGES" >> "$LOG"
for img in $IMAGES; do
  echo "--- $img" >> "$LOG"
  OUT=$(/usr/bin/trivy image --severity HIGH,CRITICAL --exit-code 0 --no-progress "$img" 2>&1)
  echo "$OUT" | tail -20 >> "$LOG"
  TOTAL=$(echo "$OUT" | grep -m1 "Total:" | xargs)
  if [ -n "$TOTAL" ]; then
    echo "SUMMARY: $img $TOTAL" >> "$LOG"
  else
    echo "SUMMARY: $img no HIGH/CRITICAL findings" >> "$LOG"
  fi
done
echo "[$(date -Iseconds)] cve_scan done" >> "$LOG"
exit 0
