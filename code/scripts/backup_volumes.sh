#!/bin/bash
# backup_volumes.sh - tar-based nightly backup of named docker volumes.
# Kopia repo is NOT connected; this replaces the phantom backup-volumes check
# with a real, verifiable volume backup. Prunes backups older than 7 days.
set -uo pipefail
DEST=/home/rohit/backups/volumes/$(date +%Y%m%d)
mkdir -p "$DEST"
LOG=/home/rohit/.hermes/logs/backup_volumes.log
count=0; failed=0
for vol in $(docker volume ls -q); do
  if docker run --rm -v "$vol":/data:ro -v "$DEST":/backup alpine tar czf "/backup/${vol}.tgz" -C /data . 2>>/dev/null; then
    count=$((count+1))
  else
    echo "[$(date -Iseconds)] FAIL: $vol" >> "$LOG"
    failed=$((failed+1))
  fi
done
# prune >7 days
find /home/rohit/backups/volumes -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} + 2>/dev/null
echo "[$(date -Iseconds)] volumes backed up: $count, failed: $failed, size: $(du -sh "$DEST" | cut -f1)" >> "$LOG"
[ "$failed" -eq 0 ]
