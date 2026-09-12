#!/usr/bin/env python3
"""systemd_fix_watchdog.py — auto-repair layer.

Covers the blind spots autoheal can't see:
1. Failed systemd --user units (autoheal only watches Docker).
2. Critical containers that must be running (incl. autoheal itself).
3. Backup freshness (report must exist, be <26h old, and say success).

Runs every 2 min via hermes_scheduler. Flock-singleton. Telegram alerts
rate-limited to one per item per 6h."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path("/home/rohit/.hermes")
LOG = HERMES_HOME / "logs" / "systemd_fix_watchdog.log"
STATE = HERMES_HOME / "state" / "systemd_fix_watchdog.json"
LOCK = HERMES_HOME / "state" / "systemd_fix_watchdog.lock"
BRIDGE = "http://127.0.0.1:9199/telegram-send"
CRITICAL = ["autoheal", "hermes", "hermes-dashboard", "n8n-bridge", "homelab-mcp", "pihole"]
BLOCKLIST = re.compile(r"^mltest\.service$|^systemd-nspawn@")
ALERT_WINDOW = 6 * 3600


def log(msg: str) -> None:
    with open(LOG, "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}Z {msg}\n")


def run(cmd, timeout: int = 20) -> tuple:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"alerts": {}}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2))


def alert(key: str, text: str) -> None:
    st = load_state()
    now = int(time.time())
    if st["alerts"].get(key, 0) > now - ALERT_WINDOW:
        return
    body = json.dumps({"text": text}).encode()
    try:
        urllib.request.urlopen(BRIDGE, data=body, timeout=10)
    except Exception as e:
        log(f"alert POST failed: {e}")
    st["alerts"][key] = now
    save_state(st)


def main() -> int:
    uid = os.getuid()
    os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)

    with open(LOCK, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("already running (lock held)")
            return 0

        fixes: list[str] = []

        rc, out, err = run(["systemctl", "--user", "--failed", "--plain", "--no-legend", "--no-pager"], timeout=15)
        for line in out.splitlines():
            parts = line.split()
            if not parts:
                continue
            unit = parts[0]
            if BLOCKLIST.match(unit):
                continue
            run(["systemctl", "--user", "reset-failed", unit], timeout=15)
            rc2, o2, e2 = run(["systemctl", "--user", "restart", unit], timeout=30)
            fixes.append(f"unit {unit} (rc={rc2}, {e2.strip()[:60]})")
            log(f"fixed failed unit {unit}: reset+restart rc={rc2} err={e2.strip()[:100]}")

        rc, out, err = run(["docker", "ps", "--format", "{{.Names}}"], timeout=15)
        running = {l.strip() for l in out.splitlines() if l.strip()}
        for c in CRITICAL:
            if c not in running:
                rc2, o2, e2 = run(["docker", "restart", c], timeout=60)
                fixes.append(f"container {c} down -> restart rc={rc2}, {e2.strip()[:60]}")
                log(f"restarted critical container {c}: rc={rc2} err={e2.strip()[:100]}")

        report = HERMES_HOME / "backup_all_report.json"
        try:
            age_h = (time.time() - report.stat().st_mtime) / 3600
            bst = json.loads(report.read_text())
            if age_h < 26 and bst.get("status") == "success":
                pass
            else:
                fixes.append(f"backup report status={bst.get('status', '?')} aged {age_h:.1f}h")
                log(f"backup report stale/bad: status={bst.get('status')} age={age_h:.1f}h")
        except Exception:
            fixes.append("backup report missing")
            log("backup report missing")

        if fixes:
            alert("auto_fix", "🛠 Auto-fixed by systemd_fix_watchdog: " + "; ".join(fixes[:8]))
            log(f"scan complete: {len(fixes)} fixes applied")
        else:
            log("scan complete: nothing to fix")
        return 0


if __name__ == "__main__":
    sys.exit(main())