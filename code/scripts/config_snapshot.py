#!/usr/bin/env python3
"""Config Snapshot — capture current state for diff/rollback.

Usage:
  config_snapshot.py save     # Save current state as latest
  config_snapshot.py diff     # Diff latest vs previous
  config_snapshot.py list     # List all snapshots
"""
import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/home/rohit/.hermes"))
SNAPSHOT_DIR = HERMES_HOME / "data" / "snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

def capture() -> dict:
    return {
        "timestamp": datetime.now().isoformat(),
        "containers": _get_docker_ps(),
        "models": _get_model_config(),
        "cron": _get_crontab(),
        "disk": _get_disk(),
    }

def _get_docker_ps() -> list[str]:
    r = subprocess.run(["docker", "ps", "--format", "{{.Names}}:{{.Status}}"],
                       capture_output=True, text=True, timeout=10)
    return sorted(r.stdout.strip().split("\n")) if r.stdout.strip() else []

def _get_model_config() -> dict:
    cfg = {}
    try:
        db = HERMES_HOME / "state.db"
        if db.exists():
            r = subprocess.run(["sqlite3", str(db), "SELECT model, COUNT(*) FROM sessions GROUP BY model ORDER BY COUNT(*) DESC LIMIT 5"],
                             capture_output=True, text=True, timeout=5)
            cfg["recent_models"] = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
    except: pass
    return cfg

def _get_crontab() -> str:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
    return r.stdout.strip() or ""

def _get_disk() -> dict:
    r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
    parts = r.stdout.strip().split("\n")[-1].split()
    return {"total": parts[1], "used": parts[2], "pct": parts[4]} if len(parts) >= 5 else {}

def save():
    data = capture()
    path = SNAPSHOT_DIR / f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(data, indent=2))
    (SNAPSHOT_DIR / "latest.json").write_text(json.dumps(data, indent=2))
    print(f"Snapshot saved: {path.name}  ({len(data['containers'])} containers, disk {data['disk'].get('pct','?')})")

def diff():
    latest = SNAPSHOT_DIR / "latest.json"
    if not latest.exists():
        print("No snapshot to diff against. Run 'save' first.")
        return
    prev = json.loads(latest.read_text())
    curr = capture()
    changes = []
    prev_ctr = set(prev.get("containers", []))
    curr_ctr = set(curr.get("containers", []))
    for c in sorted(curr_ctr - prev_ctr):
        changes.append(f"  ADDED: {c}")
    for c in sorted(prev_ctr - curr_ctr):
        changes.append(f"  REMOVED: {c}")
    prev_disk = prev.get("disk", {}).get("pct", "?")
    curr_disk = curr.get("disk", {}).get("pct", "?")
    if prev_disk != curr_disk:
        changes.append(f"  DISK: {prev_disk} -> {curr_disk}")
    if changes:
        print("Changes since last snapshot:\n" + "\n".join(changes))
    else:
        print("No changes since last snapshot.")

def list_snapshots():
    snaps = sorted(SNAPSHOT_DIR.glob("snapshot_*.json"), reverse=True)
    if not snaps:
        print("No snapshots found.")
        return
    print(f"Snapshots ({len(snaps)}):")
    for s in snaps[:10]:
        print(f"  {s.name} ({s.stat().st_size}b)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
    elif sys.argv[1] == "save":
        save()
    elif sys.argv[1] == "diff":
        diff()
    elif sys.argv[1] == "list":
        list_snapshots()
    else:
        print(f"Unknown: {sys.argv[1]}")
