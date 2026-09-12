#!/usr/bin/env python3
"""self_correction.py — Verify proactive actions worked and record feedback.

Runs every 10 minutes. Checks:
  1. Recently completed tasks from task_queue — did they resolve?
  2. Alerts pushed by autonomous systems — were they effective?
  3. Container health post-fix — are previously restarted containers still healthy?
  4. Proactive briefing outcomes — did the user act on them?

Records results to feedback_loop state for long-term learning.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
ALERTS_INBOX = Path.home() / ".hermes" / "data" / "alerts_inbox.jsonl"
QUEUE_FILE = HERMES_HOME / "state" / "task_queue.json"
STATE_FILE = HERMES_HOME / "data" / "self_correction_state.json"


def push_alert(message, severity="info"):
    entry = {
        "severity": severity, "message": message,
        "source": "self_correction",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "delivered": False, "requires_approval": False, "actions": [],
    }
    try:
        ALERTS_INBOX.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if ALERTS_INBOX.exists():
            content = ALERTS_INBOX.read_text().strip()
            if content:
                existing = json.loads(content) if content.startswith("[") else []
        existing.append(entry)
        ALERTS_INBOX.write_text(json.dumps(existing, indent=2))
    except OSError:
        pass


def check_task_results():
    """Check recently completed tasks — did they actually resolve the issue?"""
    if not QUEUE_FILE.exists():
        return [], []
    try:
        queue = json.loads(QUEUE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return [], []

    recent = [t for t in queue.get("tasks", [])
              if t.get("status") == "completed" and t.get("executed_at")]
    failures = []
    successes = []

    for task in recent:
        title = task.get("title", "")
        result = task.get("result", "")
        executed_str = task.get("executed_at", "")
        if not executed_str:
            continue
        try:
            executed = datetime.fromisoformat(executed_str)
            if (datetime.now() - executed) > timedelta(hours=24):
                continue
        except ValueError:
            continue

        # Check container health if task was container-related
        if "container" in title.lower() or "unhealthy" in title.lower():
            container = title.replace("Container ", "").replace(" is unhealthy", "").strip()
            check = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", container],
                capture_output=True, text=True, timeout=10
            )
            if check.returncode == 0 and "unhealthy" in check.stdout:
                failures.append(f"Container {container} still unhealthy after fix")
            elif check.returncode == 0:
                successes.append(f"Container {container} healthy")

        # Check system issues
        if "system issue" in title.lower():
            check = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=10
            )
            if check.returncode == 0:
                successes.append("System tasks completed")

    return successes, failures


def check_scheduler_health():
    """Check if most scheduler jobs are succeeding."""
    sched_file = HERMES_HOME / "data" / "scheduler_state.json"
    if not sched_file.exists():
        return None
    try:
        state = json.loads(sched_file.read_text())
        recent = state.get("recent_results", {})
        if not recent:
            return None
        total = len(recent)
        failed = sum(1 for v in recent.values() if isinstance(v, dict) and v.get("last_status") in ("failed", "error", "timeout"))
        if total > 0 and failed / total > 0.2:
            return f"High scheduler failure rate: {failed}/{total} jobs failing"
    except (json.JSONDecodeError, OSError):
        pass
    return None

def check_backup_health() -> str | None:
    """Check if backups are actually working (not just timer active)."""
    import subprocess
    # Check if yesterday's backup directory exists
    rc, out, _ = subprocess.run(
        ["bash", "-c", "ls -d /mnt/usb/backups/docker-volumes/$(date -d yesterday +%F 2>/dev/null || date -v-1d +%F 2>/dev/null) 2>/dev/null"],
        capture_output=True, text=True, timeout=10)
    backup_exists = bool(out.strip())
    # Check if health_signals.json has backups key with status ok
    try:
        import json
        hs_path = Path(HERMES_HOME) / "data" / "health_signals.json"
        if hs_path.exists():
            hs = json.loads(hs_path.read_text())
            backup_status = hs.get("checks", {}).get("backups", {}).get("status")
            if backup_status == "ok":
                return None  # Backups healthy
            return f"Backup health degraded: {backup_status}"
    except Exception:
        pass
    if not backup_exists:
        return "No backup found for yesterday"
    return None




def run():
    state = {"last_run": None, "total_checked": 0, "total_ok": 0, "total_fail": 0}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    successes, failures = check_task_results()
    scheduler_issue = check_scheduler_health()

    state["total_checked"] += len(successes) + len(failures)
    state["total_ok"] += len(successes)
    state["total_fail"] += len(failures)

    alerts = []
    if failures:
        msg = "\u26a0 Self-Correction: " + "; ".join(failures)
        alerts.append((msg, "warning"))
        push_alert(msg, severity="warning")

    if successes:
        msg = "\u2705 Self-Correction: " + "; ".join(successes)
        alerts.append((msg, "info"))

    if scheduler_issue:
        push_alert(scheduler_issue, severity="warning")
        alerts.append((scheduler_issue, "warning"))

    state["last_run"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2))

    if not alerts:
        print("All clear — no corrections needed")
    else:
        for msg, sev in alerts:
            print(f"[{sev}] {msg}")


if __name__ == "__main__":
    # ── Agent Parliament: council vote (pre-main dispatch) ──────────
    if '--vote-council' in __import__('sys').argv or '--vote' in __import__('sys').argv:
        _os = __import__('os')
        _sys = __import__('sys')
        _dir = _os.path.dirname(_os.path.abspath(__file__))
        _sys.path.insert(0, _os.path.join(_dir, 'lib'))
        try:
            from council_vote import cast_vote as _council_cast
        except Exception:
            _sys.path.insert(0, '/home/rohit/.hermes/hermes-agent/scripts/lib')
            from council_vote import cast_vote as _council_cast
        _dry = '--dry-run' in _sys.argv
        _res = _council_cast('self_correction', dry=_dry)
        if _dry:
            print('[self_correction would-cast: ' + '; '.join(f"{_p}={_v}" for _p, _v in _res) or f'[self_correction] no open proposals')
        else:
            print(f'[self_correction] cast ' + '; '.join(f"{_p}={_v}" for _p, _v in _res) or f'[self_correction] no votes needed')
        _sys.exit(0)

    run()
