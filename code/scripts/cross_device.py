#!/usr/bin/env python3
"""cross_device.py — Cross-Device Memory Sync (portable working state).

Writes a compact `working_state.json` into the git-backed collaborator-memory
repo. Any device (this Mac, phone, another homelab) can `git pull` the memory
repo and read the file to know: what's top-of-mind, what's active, what got
done today. The existing memory_sync job propagates it to GitHub automatically.

Store: ~/.hermes/collaborator-memory/state/working_state.json

CLI:
  python3 cross_device.py snapshot    # regenerate + commit working_state.json
  python3 cross_device.py --verify    # print the last snapshot (any device)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent_kits import HERMES_HOME, read_json, now_iso

_REPO = HERMES_HOME / "collaborator-memory"
_OUT = _REPO / "state" / "working_state.json"


def _git(argv: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(_REPO), *argv],
                          capture_output=True, text=True, timeout=timeout)


def _snapshot() -> dict:
    """Collect the current working state into a dict."""
    # top priorities from intent tracker
    priorities = []
    try:
        import intent_tracker
        priorities = [{"id": i["id"], "title": i["title"], "priority": i.get("priority")}
                      for i in intent_tracker.priorities(5)]
    except Exception:
        pass

    # active commitment count
    commitments = 0
    commitments_list = []
    try:
        from agent_kits import load_commitments
        commitments_list = [c for c in load_commitments() if c.get("status") == "open"]
        commitments = len(commitments_list)
    except Exception:
        pass

    # today's done intents
    done_today = 0
    try:
        import intent_tracker as _it
        state = read_json(HERMES_HOME / "state" / "intent_state.json", {})
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        hidden = datetime.now(timezone.utc)
        done_today = sum(
            1 for it in state.get("intents", [])
            if it.get("status") == "done" and str(it.get("done_at", ""))[:10] == today)
    except Exception:
        pass

    # last nightly review
    last_review = ""
    try:
        from agent_kits import STATE
        rs = read_json(STATE / "daily_review_state.json", {})
        last_review = rs.get("last_review", "")
    except Exception:
        pass

    # health line
    health = ""
    try:
        import health_tracker
        hl = health_tracker.status_line()
        if hl and hl != "no data yet":
            health = hl
    except Exception:
        pass

    return {
        "schema": 1,
        "device": "home-hp",
        "updated_at": now_iso(),
        "priorities": priorities,
        "open_commitments": commitments,
        "done_intents_today": done_today,
        "last_review": last_review,
        "health": health,
    }


def snapshot() -> dict:
    snap = _snapshot()
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(snap, indent=2))
    # auto-commit if the repo is a git repo (memory_sync will push it)
    if (_REPO / ".git").exists():
        _git(["add", "state/working_state.json"])
        r = _git(["commit", "-q", "-m", f"state: working_state snapshot {datetime.now():%Y-%m-%d %H:%M}"])
        # ignore "nothing to commit" error — that's fine
    return snap


def verify() -> dict:
    if not _OUT.exists():
        return {"ok": False, "error": "no working_state.json yet (run snapshot first)"}
    return read_json(_OUT, {"ok": False, "error": "corrupt"})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)
    if args.verify:
        print(json.dumps(verify(), indent=2, default=str))
        return 0
    snap = snapshot()
    print(json.dumps(snap, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())