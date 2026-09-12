#!/usr/bin/env python3
"""sync_compose_changes.py — Detect compose file changes and propagate.

Called by hermes_scheduler.py every minute. Hashes all compose YAML files and
compared to a stored baseline. When the set changes, runs post_compose_change.sh
which reconciles containers.json, syncs the service registry, prunes dangling
volumes, and reloads Traefik.

This closes the gap between 'someone edits a compose file' and 'all dependent
systems (health monitor, traefik, registry, backup) know about it'.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path.home() / ".hermes"
STATE = HERMES / "data" / ".compose_signatures.json"
COMPOSE_DIRS = [
    Path("/home/rohit/services/docker/compose"),
]
HOOK = Path("/home/rohit/.hermes/hooks/post_compose_change.sh")
LOG = HERMES / "logs" / "sync_compose_changes.log"


def _all_compose_files() -> dict[str, str]:
    """Return {path: sha256} for every .yml/.yaml file we should watch."""
    files = {}
    for d in COMPOSE_DIRS:
        if not d.exists():
            continue
        for ext in ("*.yml", "*.yaml"):
            for f in d.rglob(ext):
                if ".bak" in f.name:
                    continue
                try:
                    h = hashlib.sha256(f.read_bytes()).hexdigest()
                    files[str(f)] = h
                except (PermissionError, OSError):
                    pass
    return files


def main():
    signatures = {}
    if STATE.exists():
        try:
            signatures = json.loads(STATE.read_text())
        except (json.JSONDecodeError, OSError):
            signatures = {}

    current = _all_compose_files()

    changed = False
    added = set(current) - set(signatures)
    removed = set(signatures) - set(current)
    modified = {k for k in (set(current) & set(signatures)) if current[k] != signatures[k]}

    if added or removed or modified:
        changed = True

    if not changed:
        return  # nothing to do

    msg = f"[{datetime.now(timezone.utc).isoformat()}] compose change detected"
    detail = []
    if added:
        detail.append(f"added: {sorted(added)}")
    if removed:
        detail.append(f"removed: {sorted(removed)}")
    if modified:
        detail.append(f"modified: {sorted(modified)}")
    line = msg + (" — " + ", ".join(detail) if detail else "") + "\n"

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(line)

    if HOOK.exists():
        try:
            subprocess.run(["bash", str(HOOK)], timeout=180, check=False)
            with open(LOG, "a") as f:
                f.write(f"[{datetime.now(timezone.utc).isoformat()}] post_compose_change.sh triggered\n")
        except subprocess.TimeoutExpired:
            with open(LOG, "a") as f:
                f.write(f"[{datetime.now(timezone.utc).isoformat()}] post_compose_change.sh TIMEOUT\n")
        except Exception as e:
            with open(LOG, "a") as f:
                f.write(f"[{datetime.now(timezone.utc).isoformat()}] hook error: {e}\n")
    else:
        with open(LOG, "a") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] hook {HOOK} not found\n")

    STATE.write_text(json.dumps(current, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
