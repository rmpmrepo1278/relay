#!/bin/bash
set -euo pipefail

LOG_DIRS=(
  "/home/rohit/.hermes/logs"
)

DATE=$(date +%Y%m%d)

for base in "${LOG_DIRS[@]}"; do
  [ -d "$base" ] || continue

  find "$base" -name "*.log" ! -name "*.log.*" ! -name "*\.gz" -size +5M | while read f; do
    gzip -c "$f" > "${f}.${DATE}.gz"
    truncate -s 0 "$f"
    echo "[$DATE] Rotated $f"
  done

  tf="$base/thinking-traces.jsonl"
  if [ -f "$tf" ] && [ "$(stat -c%s "$tf" 2>/dev/null || stat -f%z "$tf" 2>/dev/null)" -gt 5000000 ]; then
    tail -2000 "$tf" > "${tf}.tmp" && mv "${tf}.tmp" "$tf"
    echo "[$DATE] Truncated $tf"
  fi

  for pf in "$base/proxy.log" "$base/proxy.log.1"; do
    if [ -f "$pf" ] && [ "$(stat -c%s "$pf" 2>/dev/null || stat -f%z "$pf" 2>/dev/null)" -gt 5000000 ]; then
      tail -2000 "$pf" > "${pf}.tmp" && mv "${pf}.tmp" "$pf"
      echo "[$DATE] Truncated $pf"
    fi
  done

  find "$base" -name "*.gz" -mtime +30 -delete 2>/dev/null
done

CMEM=/home/rohit/.hermes/claudemem_harvest_state.json
if [ -f "$CMEM" ] && [ "$(stat -c%s "$CMEM" 2>/dev/null || stat -f%z "$CMEM" 2>/dev/null)" -gt 1000000 ]; then
  python3 -c "
import json
with open() as f:
    d = json.load(f)
if isinstance(d, list) and len(d) > 500:
    with open(, w) as f:
        json.dump(d[-500:], f, indent=2)
"
fi
echo "[$DATE] Log rotation complete"
