#!/bin/bash
# docker_ghost_check.sh — Detect ghost/orphaned Docker containers.
# A "ghost" is a running container not in the expected compose projects.

set -euo pipefail

LOG_FILE="/home/rohit/.hermes/logs/docker_ghost_check.log"
mkdir -p "$(dirname "$LOG_FILE")"

EXPECTED_PATTERNS="hermes-webui|mentedb|paperless|homelab-exec|mcp-gateway|paper-agent|authentik|healthchecks|mission-control|khoj|opencontext|docker-mcp|file-mcp|paperless-mcp|global-chat|hermes-memory|backup-mcp|rss-mcp|browser-use|network-mcp|git-mcp|doctor-mcp|autoheal|portainer|homepage|immich|grafana|promtail|qdrant|loki|prometheus|alertmanager|node-exporter|watchtower|homeassistant|openwebui|calibre-web|vaultwarden|searxng|shlink|linkwarden|bookstack|freellmapi|cadvisor|nginx-proxy-manager|docker-socket-proxy|redis|pihole"

ghosts=0

while IFS= read -r container; do
  [ -z "$container" ] && continue
  if ! echo "$container" | grep -qEi "$EXPECTED_PATTERNS"; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] GHOST: $container" >> "$LOG_FILE"
    ghosts=$((ghosts + 1))
  fi
done < <(docker ps --format '{{.Names}}' 2>/dev/null || true)

if [ "$ghosts" -eq 0 ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ghost_check: 0 ghosts" >> "$LOG_FILE"
  echo "OK: 0 ghost containers"
else
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ghost_check: $ghosts ghosts found" >> "$LOG_FILE"
  echo "WARNING: $ghosts ghost containers detected"
fi
