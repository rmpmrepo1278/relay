#!/bin/bash
# cve_scan.sh - weekly trivy scan of key images. Report-only (exit 0) so the
# scheduler job never false-fails; results logged for review.
set -uo pipefail
LOG=/home/rohit/.hermes/logs/cve_scan.log
IMAGES="hermes-agent:latest immich-server:release paperless-ngx/paperless-ngx:2.20.15 traefik:latest"
for img in $IMAGES; do
  /usr/bin/trivy image --severity HIGH,CRITICAL --exit-code 0 --no-progress "$img" 2>&1 | tail -20 >> "$LOG"
done
echo "[$(date -Iseconds)] cve_scan done" >> "$LOG"
exit 0
