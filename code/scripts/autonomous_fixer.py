"""autonomous_fixer.py — Auto-remediation for common homelab failures.

Runs every 10 minutes via self_correction (called by mind_loop's _run_autoself_fixer).
Checks:
  1. Unhealthy or exited containers → restart them
  2. Backup failures → retry the backup
  3. Down services → attempt restart
  4. Docker daemon issues → alert

All actions are logged to data/autonomous_fixer_log.jsonl for audit.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
LOG_FILE = HERMES_HOME / "data" / "autonomous_fixer_log.jsonl"
DOCKER = "docker"

def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)

def _log_action(action: str, status: str, detail: str = "") -> None:
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "action": action, "status": status, "detail": detail}
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

def _restart_container(name: str) -> bool:
    rc, out, err = _run(["docker", "restart", name], timeout=60)
    _log_action(f"restart_{name}", "attempted", f"rc={rc} out={out}")
    return rc == 0

def _check_backups() -> dict:
    import subprocess as sp
    rc, out, _ = _run(["bash", "-c", "ls -d /mnt/usb/backups/docker-volumes/$(date -d yesterday +%F 2>/dev/null || date -v-1d +%F 2>/dev/null) 2>/dev/null"], timeout=10)
    backup_exists = bool(out.strip())
    rc2, out2, _ = _run(["systemctl", "--user", "is-active", "hermes-backup.timer"], timeout=5)
    timer_active = out2.strip() == "active"
    return {"backup_exists": backup_exists, "timer_active": timer_active}

def _retry_backup() -> bool:
    _log_action("retry_backup", "attempted")
    rc, out, err = _run(["bash", "/home/rohit/scripts/backup_docker_volumes.sh"], timeout=120)
    success = rc == 0
    _log_action("retry_backup", "success" if success else "failed", f"rc={rc} err={err}")
    return success

def run_fix_cycle() -> dict:
    actions = []
    # 1. Check for unhealthy containers
    rc, out, _ = _run(["docker", "ps", "--filter", "health=unhealthy", "--format", "{{.Names}}"])
    if rc == 0 and out:
        for name in out.strip().split("\n"):
            name = name.strip()
            if name and _restart_container(name):
                actions.append(f"Restarted unhealthy {name}")
    # 2. Check for exited containers
    rc, out, _ = _run(["docker", "ps", "--filter", "status=exited", "--format", "{{.Names}}"])
    if rc == 0 and out:
        for name in out.strip().split("\n"):
            name = name.strip()
            if name and _restart_container(name):
                actions.append(f"Restarted exited {name}")
    # 3. Check backups
    backup_status = _check_backups()
    if not backup_status["backup_exists"]:
        _log_action("backup_missing", "detected")
        if _retry_backup():
            actions.append("Retried failed backup")
        else:
            actions.append("Backup retry failed - check disk/internet")
    # 4. Check hermes compose
    rc, _, _ = _run(["docker", "ps", "--filter", "name=hermes", "--filter", "status=running", "--format", "{{.Status}}"])
    if rc != 0 or not rc:
        _log_action("hermes_down", "detected")
        rc2, _, _ = _run(["docker", "compose", "-f", "/home/rohit/docker-compose.yml", "restart", "hermes"], timeout=60)
        if rc2 == 0:
            actions.append("Restarted hermes compose")
    _log_action("run_fix_cycle", "completed", f"actions={len(actions)}")
    return {"actions": actions, "count": len(actions)}

if __name__ == "__main__":
    result = run_fix_cycle()
    print(json.dumps(result))
