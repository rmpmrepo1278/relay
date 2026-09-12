#!/usr/bin/env python3
"""Deduplicate experiments.jsonl and prune stale capsule data."""
import json
from pathlib import Path
from datetime import datetime, timezone

HERMES_HOME = Path.home() / ".hermes"
EXPERIMENTS_FILE = HERMES_HOME / "experiments.jsonl"
CAPSULES_FILE = HERMES_HOME / "capsules" / "outcomes.jsonl"

def deduplicate_jsonl(path: Path, dedup_keys=("id", "timestamp")) -> int:
    """Remove duplicate entries based on key combo. Return count removed."""
    if not path.exists():
        return 0
    seen = set()
    unique = []
    removed = 0
    for line in path.read_text().strip().split("\n"):
        try:
            obj = json.loads(line)
            key = tuple(str(obj.get(k, "")) for k in dedup_keys[:1])  # dedup by id only
            if key not in seen:
                seen.add(key)
                unique.append(line)
            else:
                removed += 1
        except:
            removed += 1
    path.write_text("\n".join(unique) + "\n" if unique else "")
    return removed

def prune_capsules(max_lines: int = 200) -> int:
    """Keep only last N capsule entries."""
    if not CAPSULES_FILE.exists():
        return 0
    lines = CAPSULES_FILE.read_text().strip().split("\n")
    if len(lines) <= max_lines:
        return 0
    pruned = len(lines) - max_lines
    CAPSULES_FILE.write_text("\n".join(lines[-max_lines:]) + "\n")
    return pruned

if __name__ == "__main__":
    e = deduplicate_jsonl(EXPERIMENTS_FILE)
    c = prune_capsules(500)
    print(json.dumps({"experiments_removed": e, "capsules_pruned": c}))
