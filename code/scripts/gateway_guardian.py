#!/usr/bin/env python3
"""
gateway_guardian.py — Monitor hermes-gateway health and auto-rollback bad snapshots.

Runs every 5 minutes via cron. Checks:
1. Is the gateway process running?
2. Can it import its entry-point module?
3. Is Telegram connected?
4. If a recent auto-fix snapshot preceded a failure, rollback to pre-snapshot.

This is the safety net that prevents the "hermes_cli deleted → 3226 restarts" scenario.
"""

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from syslog_emit import syslog_info as _syslog_info, syslog_warning as _syslog_warning
except Exception:
    _syslog_info = _syslog_warning = lambda *a, **k: None

# ponytail: global lock, per-gateway locks if we ever shard
_lock_fd = open("/tmp/flock_gateway_guardian.lock", "w")
try:
    fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    print("gateway_guardian: already running, exiting.", file=sys.stderr)
    sys.exit(0)

GATEWAY_STATE = Path.home() / ".hermes" / "gateway_state.json"
AGENT_DIR = Path.home() / ".hermes" / "hermes-agent"
SNAPSHOT_PREFIX = "auto-fix-snapshot:"
MAX_SNAPSHOT_AGE_SEC = 3600  # Only consider snapshots < 1 hour old
TELEGRAM_API = "https://api.telegram.org"

# Recurring-outage escalation: alert via Telegram after N consecutive
# Telegram-unreachable checks, and re-alert at each interval after that.
COUNTER_FILE = Path.home() / ".hermes" / "data" / "gateway_telegram_counter.json"
TELEGRAM_TOKEN_FILE = Path.home() / ".hermes" / ".telegram_token"
ALERT_THRESHOLD = 3  # checks (~15 min at 5-min cadence)


def send_telegram(text: str) -> None:
    """Send a Telegram message using the gateway's bot token file."""
    import urllib.parse
    try:
        if not TELEGRAM_TOKEN_FILE.exists():
            return
        token = TELEGRAM_TOKEN_FILE.read_text().strip()
        if not token:
            return
        chat_id = os.environ.get("TELEGRAM_HOME_CHANNEL", "-1003976074764")
        import urllib.request
        data = urllib.parse.urlencode({
            "chat_id": chat_id, "text": text[:4000],
        }).encode()
        req = urllib.request.Request(
            f"{TELEGRAM_API}/bot{token}/sendMessage",
            data=data,
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception:
        pass


def _read_counter() -> dict:
    try:
        return json.loads(COUNTER_FILE.read_text())
    except Exception:
        return {"consecutive": 0, "last_alerted_at": None}


def _write_counter(counter: dict) -> None:
    COUNTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    COUNTER_FILE.write_text(json.dumps(counter))


def telegram_unreachable_escalate(now_unreachable: bool) -> list[str]:
    """Track consecutive Telegram-unreachable checks; alert on threshold. Returns actions."""
    counter = _read_counter()
    if now_unreachable:
        counter["consecutive"] = counter.get("consecutive", 0) + 1
        n = counter["consecutive"]
        active = []
        if n == ALERT_THRESHOLD:
            active.append(f"Telegram API unreachable for {n} consecutive checks (escalated)")
            send_telegram(f"⚠️ Hermes gateway: Telegram API unreachable for ~{n * 5} minutes. "
                          f"No self-recovery could confirm gateway-side connectivity.")
        elif n > ALERT_THRESHOLD and (n % ALERT_THRESHOLD) == 0:
            active.append(f"Telegram API still unreachable ({n} checks)")
            send_telegram(f"⏳ Hermes gateway: Telegram API still unreachable after ~{n * 5} minutes.")
        _write_counter(counter)
        return active
    else:
        # Recovered — reset counter
        if counter.get("consecutive", 0) != 0:
            _write_counter({"consecutive": 0, "last_alert_at": None})
        return []


def run(cmd: str, check: bool = False) -> tuple[int, str]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return r.returncode, (r.stdout + r.stderr).strip()


def gateway_active() -> bool:
    rc, _ = run("docker ps --filter name=hermes --filter status=running --format \"{{.Names}}\" | grep -q hermes")
    return rc == 0


def telegram_reachable() -> bool:
    rc, _ = run(f"curl -sf -o /dev/null --connect-timeout 5 {TELEGRAM_API}")
    return rc == 0


def module_importable() -> bool:
    venv_python = AGENT_DIR / ".venv" / "bin" / "python"
    rc, out = run(f"{venv_python} -c 'import hermes_cli.main; import gateway.run; print(1)'")
    return rc == 0


def recent_auto_fix_snapshots(limit: int = 5) -> list[str]:
    """Return SHAs of recent auto-fix-snapshot commits."""
    rc, out = run(
        f"cd {AGENT_DIR} && git log --oneline --grep='{SNAPSHOT_PREFIX}' -{limit} --format='%H %s'"
    )
    if rc != 0 or not out:
        return []
    commits = []
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            sha, subject = parts
            # Check age
            rc2, ts = run(f"cd {AGENT_DIR} && git log -1 --format='%ct' {sha}")
            if rc2 == 0 and ts.strip().isdigit():
                age = time.time() - int(ts.strip())
                if age < MAX_SNAPSHOT_AGE_SEC:
                    commits.append(sha)
    return commits


def pre_snapshot_commit(snapshot_sha: str) -> str | None:
    """Get the commit just before the snapshot (the known-good state)."""
    rc, out = run(f"cd {AGENT_DIR} && git log -1 --format='%H' {sha}~1")
    if rc == 0 and out.strip():
        return out.strip()
    return None


def rollback_to(commit_sha: str) -> bool:
    """Hard reset to a known-good commit. DESTROYS working directory state."""
    rc, out = run(f"cd {AGENT_DIR} && git checkout -- . 2>&1")
    if rc != 0:
        return False
    rc, out = run(f"cd {AGENT_DIR} && git reset --hard {commit_sha} 2>&1")
    return rc == 0


def reinstall_package() -> bool:
    """Reinstall hermes-agent from PyPI as last resort."""
    venv_pip = AGENT_DIR / ".venv" / "bin" / "python"
    rc, out = run(
        f"{venv_pip} -m pip install --force-reinstall 'hermes-agent[all]' 2>&1",
    )
    return rc == 0


def restart_gateway() -> bool:
    rc, _ = run("docker compose -f /home/rohit/docker-compose.yml restart hermes 2>&1 || docker restart hermes 2>&1")
    return rc == 0


def main():
    issues = []
    actions = []

    # --- Check 1: Module importable? ---
    if not module_importable():
        issues.append("hermes_cli module not importable")
        # Try reinstall first
        actions.append("Attempting pip reinstall...")
        if reinstall_package():
            actions.append("pip reinstall succeeded")
        else:
            issues.append("pip reinstall failed")
            # Try rollback
            snapshots = recent_auto_fix_snapshots()
            for snap in snapshots:
                pre = pre_snapshot_commit(snap)
                if pre:
                    actions.append(f"Rolling back to pre-snapshot {pre[:12]}...")
                    if rollback_to(pre):
                        actions.append("Rollback succeeded, reinstalling...")
                        reinstall_package()
                        break
                    else:
                        actions.append("Rollback failed")

    # --- Check 2: Gateway running? ---
    if not gateway_active():
        issues.append("hermes-gateway not active")
        if module_importable():
            actions.append("Module OK, restarting gateway...")
            restart_gateway()
        else:
            actions.append("Module broken, gateway restart skipped (fixed above)")

    # --- Check 3: Telegram connected? ---
    if gateway_active() and not telegram_reachable():
        issues.append("Gateway running but Telegram API unreachable")
        # This is expected during ISP outage — just log, don't restart
        actions.append("Telegram API unreachable (likely ISP outage), skipping restart")
        actions.extend(telegram_unreachable_escalate(True))
    else:
        telegram_unreachable_escalate(False)

    # --- Check 4: Verify recovery after actions ---
    if actions:
        time.sleep(5)
        recovered = module_importable() and gateway_active()
        if recovered:
            actions.append("RECOVERY VERIFIED ✓")
        else:
            actions.append("RECOVERY FAILED — manual intervention needed")

    # --- Report ---
    if issues:
        state = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "issues": issues,
            "actions": actions,
            "healthy": not issues or all("RECOVERY VERIFIED" in a for a in actions),
        }
        # Write to a status file for other tools to read
        status_file = Path.home() / ".hermes" / "data" / "gateway_guardian.json"
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.write_text(json.dumps(state, indent=2))

        # Print for cron logging + syslog
        summary = f"ISSUES: {'; '.join(issues)}"
        print(f"gateway_guardian: {summary}")
        for a in actions:
            print(f"  → {a}")
        _syslog_warning("gateway_guardian", summary)
        sys.exit(0 if state["healthy"] else 1)
    else:
        # Healthy — still write status
        state = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "issues": [],
            "actions": ["all checks passed"],
            "healthy": True,
        }
        status_file = Path.home() / ".hermes" / "data" / "gateway_guardian.json"
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.write_text(json.dumps(state, indent=2))
        print("gateway_guardian: all checks passed ✓")
        _syslog_info("gateway_guardian", "all checks passed")
        sys.exit(0)


if __name__ == "__main__":
    main()
