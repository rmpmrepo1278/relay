#!/bin/bash
# cve_scan.sh - weekly trivy scan of key images. Report-only (exit 0) so the
# scheduler job never false-fails; results logged for review.
set -uo pipefail
LOG=/home/rohit/.hermes/logs/cve_scan.log
# Derive image refs from RUNNING containers so tag bumps never silently break scans
# (Sep 13 2026: immich/paperless refs were missing the ghcr.io path -> trivy FATAL
#  on 2 of 4 images while the script still exited 0; now resolved + dynamic)
IMAGES=$(docker ps --format '{{.Image}}' | grep -E 'hermes-agent|immich|paperless|traefik' | sort -u)
if [ -z "$IMAGES" ]; then
  echo "[$(date -Iseconds)] WARN: no matching images found" >> "$LOG"
  exit 0
fi
echo "[$(date -Iseconds)] cve_scan start: $IMAGES" >> "$LOG"
for img in $IMAGES; do
  echo "--- $img" >> "$LOG"
  /usr/bin/trivy image --severity HIGH,CRITICAL --exit-code 0 --no-progress "$img" 2>&1 | tail -20 >> "$LOG"
done
echo "[$(date -Iseconds)] cve_scan done" >> "$LOG"
exit 0