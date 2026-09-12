#!/bin/bash
# debloat.sh — Lean-and-clean sweep for Hermes homelab
set -euo pipefail
LOG=/home/rohit/.hermes/logs/debloat.log
echo "[$(date)] === DEBLOAT ===" >> "$LOG"

# 1. Clean old temp files
find /tmp -name "*.tmp" -user rohit -atime +1 -delete 2>/dev/null || true

# 2. Clean Python cache outside venvs
find /home/rohit/.hermes \
  -name "__pycache__" -type d \
  -not -path "*/.venv/*" -not -path "*/venv/*" \
  -exec rm -rf {} + 2>/dev/null || true
echo "Cleaned __pycache__" >> "$LOG"

# 3. Git prune (garbage collect + expire reflog)
for repo in /home/rohit/.hermes/hermes-agent; do
  if [ -d "$repo/.git" ]; then
    (cd "$repo" && git reflog expire --expire=30.days --all 2>/dev/null || true)
    (cd "$repo" && git gc --prune=30.days --aggressive 2>/dev/null || true)
    echo "GC'd: $repo" >> "$LOG"
  fi
done

# 4. Docker: remove unused networks
docker network prune -f 2>/dev/null || true
echo "Docker networks pruned" >> "$LOG"

# 5. Remove stale hermetic screens
for s in $(screen -ls 2>/dev/null | grep Detached | awk '{print $1}'); do
  screen -S "$s" -X quit 2>/dev/null || true
done

# 6. Clean stale docker build cache
docker builder prune -af --filter until=168h 2>/dev/null || true

echo "[$(date)] === DEBLOAT DONE ===" >> "$LOG"
