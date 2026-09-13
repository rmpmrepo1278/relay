#!/bin/bash
# docker_ghost_check.sh — Detect ghost/orphaned Docker containers.
# A "ghost" is a running container not in the expected inventory.
# Expected set is derived from ~/services/inventory/inventory.json (source of
# truth, 32 services) so this never drifts again (was: hardcoded stale list
# missing hermes/n8n-bridge/traefik etc.).
set -uo pipefail

LOG_FILE="/home/rohit/.hermes/logs/docker_ghost_check.log"
INVENTORY="/home/rohit/services/inventory/inventory.json"
mkdir -p "$(dirname "$LOG_FILE")"

# Pull expected container names from inventory
if [ ! -f "$INVENTORY" ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: inventory missing" >> "$LOG_FILE"
  exit 1
fi
EXPECTED=$(python3 - "$INVENTORY" << "PYEOF"
import json, sys
inv = json.load(open(sys.argv[1]))
names = [s.get("container_name") or s.get("name") for s in inv.get("services", [])]
names = [n for n in names if n]
print("|".join(sorted(names)))
PYEOF
)

ghosts=0
while IFS= read -r container; do
  [ -z "$container" ] && continue
  if ! echo "$container" | grep -qE "$EXPECTED"; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] GHOST: $container" >> "$LOG_FILE"
    ghosts=$((ghosts + 1))
  fi
done < <(docker ps --format "{{.Names}}" 2>/dev/null || true)

if [ "$ghosts" -eq 0 ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ghost_check: 0 ghosts" >> "$LOG_FILE"
  echo "OK: 0 ghost containers"
  exit 0
else
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ghost_check: $ghosts ghosts found" >> "$LOG_FILE"
  echo "WARNING: $ghosts ghost containers detected"
  exit 2
fi
