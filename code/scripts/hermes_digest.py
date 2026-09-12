#!/usr/bin/env python3
"""hermes_digest.py — Daily report of autonomous actions and system health."""
import json, sqlite3, subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone

HERMES_HOME = Path.home() / ".hermes"
DECISIONS = HERMES_HOME / "logs" / "autonomous_decisions.jsonl"
DB_PATH = HERMES_HOME / "state" / "hermes_memory.db"
DIGEST_FILE = HERMES_HOME / "logs" / "daily_digest.jsonl"

def main():
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(hours=24)

    # Actions in last 24h
    actions = []
    if DECISIONS.exists():
        for line in DECISIONS.read_text().strip().split("\n"):
            try:
                obj = json.loads(line)
                ts = obj.get("timestamp", "")
                if ts >= yesterday.isoformat():
                    actions.append(obj)
                elif ts < (yesterday - timedelta(hours=1)).isoformat():
                    break
            except:
                pass

    # Memory stats
    mem_stats = {"total_actions": 0, "in_cooldown": 0, "maxed_out": 0}
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(DB_PATH))
            mem_stats["total_actions"] = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
            mem_stats["in_cooldown"] = conn.execute("SELECT COUNT(*) FROM actions WHERE cooldown_until > ?", (now.isoformat(),)).fetchone()[0]
            mem_stats["maxed_out"] = conn.execute("SELECT COUNT(*) FROM actions WHERE count >= 3 AND outcome='fail'").fetchone()[0]
            conn.close()
        except:
            pass

    # Container health
    containers = {"total": 0, "unhealthy": 0}
    try:
        r = subprocess.run(["docker", "ps", "--format", "{{.Status}}"], capture_output=True, text=True, timeout=10)
        for line in r.stdout.strip().split("\n"):
            if line:
                containers["total"] += 1
                if "unhealthy" in line.lower():
                    containers["unhealthy"] += 1
    except:
        pass

    summary = {
        "date": now.isoformat(),
        "actions_taken": len(actions),
        "memory": mem_stats,
        "containers": containers,
        "recent_decisions": [a.get("gene", "") + ": " + a.get("action", "") for a in actions[-10:]]
    }

    DIGEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DIGEST_FILE, "a") as f:
        f.write(json.dumps(summary) + "\n")

    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
