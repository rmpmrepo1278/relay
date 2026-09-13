#!/bin/bash
# skill_index_refresh.sh - force a fresh .skills_prompt_snapshot.json rebuild.
# The agent already builds/validates the snapshot natively (prompt_builder.py:
# build_skills_system_prompt + manifest check). This wrapper forces an explicit
# rebuild inside the hermes container so ops can trigger it on demand.
set -u
SNAP=/home/rohit/.hermes/.skills_prompt_snapshot.json
BEFORE=$(stat -c %Y "$SNAP" 2>/dev/null || echo 0)
OUT=$(docker exec hermes python3 -c "
import sys
sys.path.insert(0, '/opt/data')
from agent import prompt_builder as p
p.clear_skills_system_prompt_cache(clear_snapshot=True)
text = p.build_skills_system_prompt()
print('REBUILT_OK len=%d' % len(text))
" 2>&1 | tail -1)
AFTER=$(stat -c %Y "$SNAP" 2>/dev/null || echo 0)
if echo "$OUT" | grep -q REBUILT_OK && [ "$AFTER" -ge "$BEFORE" ] && [ -s "$SNAP" ]; then
  echo "OK: $OUT | snapshot $(stat -c %s "$SNAP") bytes"
  exit 0
else
  echo "WARN: $OUT"
  exit 1
fi
