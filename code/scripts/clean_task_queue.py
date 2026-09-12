#!/usr/bin/env python3
"""Clean stale tasks from task_queue.json — archive anything >7 days old."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TASK_FILE = Path.home() / ".hermes" / "state" / "task_queue.json"
CUTOFF_DAYS = 7

def _parse_ts(raw: str) -> datetime:
    try:
        ts = datetime.fromisoformat(raw)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def clean():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=CUTOFF_DAYS)

    if not TASK_FILE.exists():
        print("No task queue found")
        return

    data = json.loads(TASK_FILE.read_text())
    tasks = data.get("tasks", [])
    archived = data.get("archived", [])

    kept = []
    stale = []
    for t in tasks:
        ts = _parse_ts(t.get("created", ""))

        if ts < cutoff and t.get("status") in ("pending", "escalated"):
            stale.append(t)
        else:
            kept.append(t)

    if stale:
        archived.extend(stale)
        for t in stale:
            age = (now - _parse_ts(t.get("created", now.isoformat()))).days
            print(f"  Archived: [{t['status']}] P{t.get('priority', '?')} {t['title'][:60]} ({age}d old)")

    data["tasks"] = kept
    data["archived"] = archived
    data["last_cleaned"] = now.isoformat()
    TASK_FILE.write_text(json.dumps(data, indent=2))
    print(f"\nKept {len(kept)} tasks, archived {len(stale)} stale tasks")

if __name__ == "__main__":
    clean()
