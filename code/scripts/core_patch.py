#!/usr/bin/env python3
"""core_patch.py — weekly patch-with-rollback for the Hermes core image.

Builds the hermes-agent image from the /home/rohit git source, recreates the
gateway/dashboard/n8n-bridge containers, waits for them to be healthy, and
rolls back to the previous image digest on any failure. Keeps a .bak image
tag for manual backout.

Usage:
    core_patch.py --dry-run   # report current state, do nothing
    core_patch.py             # patch (build + upgrade + health-gated rollback)

Scheduled weekly via hermes_scheduler."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path("/home/rohit/.hermes")
LOG = HERMES_HOME / "logs" / "core_patch.log"
STATE = HERMES_HOME / "state" / "core_patch.json"
LOCK = HERMES_HOME / "state" / "core_patch.lock"
COMPOSE = "/home/rohit/docker-compose.yml"
SRC = "/home/rohit"
SERVICES = ["gateway", "dashboard", "n8n-bridge"]
BRIDGE = "http://127.0.0.1:9199/telegram-send"
ALERT_WINDOW = 6 * 3600


def log(msg: str) -> None:
    with open(LOG, "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}Z {msg}\n")


def run(cmd, timeout: int = 300) -> tuple:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def image_id() -> str:
    rc, out, err = run(["docker", "inspect", "hermes-agent", "--format", "{{.Id}}"], timeout=15)
    return out.strip() if rc == 0 else "?"


def notify(text: str) -> None:
    body = json.dumps({"text": text}).encode()
    try:
        urllib.request.urlopen(BRIDGE, data=body, timeout=10)
    except Exception as e:
        log(f"notify failed: {e}")


def wait_healthy(names: list, timeout: int = 300) -> tuple:
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, out, _ = run(["docker", "ps", "--filter", "health=unhealthy", "--format", "{{.Names}}"], timeout=15)
        unhealthy = set(out.split())
        _, out2, _ = run(["docker", "ps", "--format", "{{.Names}}"], timeout=15)
        running = set(out2.split())
        bad = (unhealthy & set(names)) | (set(names) - running)
        if not bad:
            return True, []
        time.sleep(10)
    return False, sorted(bad)


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)

    with open(LOCK, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("already running (lock held)")
            return 0

        dry = "--dry-run" in sys.argv
        cur = image_id()
        if dry:
            rc, out, err = run(["git", "-C", SRC, "status", "--porcelain", "-z"], timeout=15)
            dirty = bool(out)
            rc2, out2, err2 = run(["git", "-C", SRC, "log", "--oneline", "-1"], timeout=15)
            rc3, out3, err3 = run(["git", "-C", SRC, "rev-parse", "--short", "HEAD"], timeout=15)
            print(f"image hermes-agent = {cur}")
            print(f"source commit       = {out3.strip()} ({out2.strip()})")
            print(f"working tree dirty  = {dirty}")
            print(f"services            = {', '.join(SERVICES)}")
            return 0

        bak = f"hermes-agent.bak-{int(time.time())}"
        log(f"start: current image {cur}")
        run(["docker", "tag", "hermes-agent", bak], timeout=30)

        rc, out, err = run(["git", "-C", SRC, "pull", "--ff-only"], timeout=120)
        if rc != 0:
            msg = f"src pull failed rc={rc}: {err.strip()[:200]}; aborting, no build" 
            log(msg)
            notify("!! core_patch: " + msg)
            run(["docker", "tag", bak, "hermes-agent"], timeout=30)
            return 1

        rc, out, err = run(["docker", "compose", "-f", COMPOSE, "build", "gateway"], timeout=2400)
        if rc != 0:
            msg = f"build failed rc={rc}: {(err or out).strip()[-200:]}; rolling back"
            log(msg)
            notify("!! core_patch: " + msg)
            run(["docker", "tag", bak, "hermes-agent"], timeout=30)
            run(["docker", "compose", "-f", COMPOSE, "up", "-d"] + SERVICES, timeout=600)
            return 1

        rc, out, err = run(["docker", "compose", "-f", COMPOSE, "up", "-d"] + SERVICES, timeout=600)
        if rc != 0:
            msg = f"up failed rc={rc}: {(err or out).strip()[-200:]}; rolling back"
            log(msg)
            notify("!! core_patch: " + msg)
            run(["docker", "tag", bak, "hermes-agent"], timeout=30)
            run(["docker", "compose", "-f", COMPOSE, "up", "-d"] + SERVICES, timeout=600)
            return 1

        ok, bad = wait_healthy(SERVICES, timeout=300)
        new = image_id()
        record = {"ts": datetime.now(timezone.utc).isoformat(), "status": "ok" if ok else "rollback",
                  "prev": cur, "new": new, "backup_tag": bak, "bad": bad}
        if not ok:
            msg = f"health gate failed on {bad}; rolling back from {new} -> {cur}"
            log(msg)
            notify("!! core_patch: " + msg)
            run(["docker", "tag", bak, "hermes-agent"], timeout=30)
            run(["docker", "compose", "-f", COMPOSE, "up", "-d"] + SERVICES, timeout=600)
            good, _ = wait_healthy(SERVICES, timeout=120)
            record["status"] = "rollback" if good else "rollback_failed"
            if not good:
                notify("!! core_patch: rollback ALSO not healthy — manual intervention needed (backup tag saved: " + bak + ")")
        else:
            notify("✅ core_patch: hermes core rebuilt " + cur[:12] + " -> " + new[:12] + " (backup " + bak + ")")
        STATE.write_text(json.dumps(record, indent=2))
        log(f"done: {record}")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())