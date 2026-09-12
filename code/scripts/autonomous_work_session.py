#!/usr/bin/env python3
"""
autonomous_work_session.py — Hermes self-initiated work sessions.

Triggers 3× daily (10am/2pm/7pm) via cron. Performs:
1. Health snapshot
2. Commitment check (overdue + upcoming)
3. Task queue review
4. Homelab triage (autonomous fixes)
5. Telegram report (via telegram_bridge)

Usage:
    python3 autonomous_work_session.py --type morning|afternoon|evening
    python3 autonomous_work_session.py --health-only
"""

from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
LOG_FILE = HERMES_HOME / "logs" / "autonomous_work.log"
SCRIPTS_DIR = HERMES_HOME / "scripts"

# Add hermes scripts to path for telegram_bridge import
sys.path.insert(0, str(SCRIPTS_DIR))


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] autonomous_work: {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def run_cmd(cmd: list, timeout: int = 30) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()
    except Exception:
        return ""


def run_script(script_name: str, *args, timeout: int = 60) -> dict:
    """Run a hermes script and return structured result."""
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        return {"success": False, "error": f"{script_name} not found", "output": ""}
    try:
        r = subprocess.run(
            [sys.executable, str(script_path)] + list(args),
            capture_output=True, text=True, timeout=timeout
        )
        return {
            "success": r.returncode == 0,
            "output": r.stdout.strip(),
            "error": r.stderr.strip() if r.returncode != 0 else "",
            "returncode": r.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout", "output": ""}
    except Exception as e:
        return {"success": False, "error": str(e), "output": ""}


def health_snapshot() -> dict:
    """Quick health snapshot."""
    snapshot = {"timestamp": datetime.now(timezone.utc).isoformat()}

    docker_out = run_cmd(["docker", "ps", "--format", "{{.Names}}: {{.Status}}"])
    containers = [l for l in docker_out.split("\n") if l]
    snapshot["docker_total"] = len(containers)
    snapshot["docker_unhealthy"] = len([c for c in containers if "Up" not in c])

    disk_out = run_cmd(["df", "-h", "/"])
    for line in disk_out.split("\n")[1:]:
        parts = line.split()
        if len(parts) >= 5:
            try:
                snapshot["disk_pct"] = int(parts[4].rstrip("%"))
            except ValueError:
                pass

    mem_out = run_cmd(["free", "-h"])
    mem_parts = mem_out.split("\n")[1].split()
    if len(mem_parts) >= 3:
        snapshot["ram_total"] = mem_parts[1]
        snapshot["ram_used"] = mem_parts[2]

    # The Hermes gateway is s6-supervised inside the `hermes` container — there
    # is no `hermes-gateway` user unit, so probe the container + hop instead.
    hermes_container = run_cmd(
        ["docker", "ps", "--filter", "name=^hermes$", "--format", "{{.Status}}"]
    )
    hop_health = run_cmd(["curl", "-s", "--max-time", "3", "http://127.0.0.1:8083/health"])
    snapshot["gateway"] = hermes_container or "hermes container down"
    snapshot["hop"] = "ok" if "status" in hop_health else "unreachable"

    return snapshot


def commitment_check() -> dict:
    """Check for overdue and upcoming commitments."""
    try:
        r = run_script("commitment_tracker.py", "status", timeout=30)
        if r["success"]:
            return {"status": "ok", "output": r["output"]}
        return {"status": "error", "error": r.get("error", "unknown")}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def task_queue_review() -> dict:
    """Review pending tasks."""
    try:
        r = run_script("task_queue.py", "list", timeout=30)
        lines = [l for l in r.get("output", "").split("\n") if l.strip()]
        return {"count": len(lines), "items": lines[:5]}
    except Exception as e:
        return {"count": 0, "error": str(e)}


def run_homelab_triage() -> dict:
    """Run homelab-triage skill's bash script for autonomous fixes."""
    triage_script = HERMES_HOME / "skills" / "homelab-triage" / "scripts" / "homelab-triage.sh"
    if not triage_script.exists():
        return {"status": "skipped", "reason": "triage script not found"}
    try:
        r = subprocess.run(
            ["bash", str(triage_script), "--fix", "--json"],
            capture_output=True, text=True, timeout=120
        )
        if r.returncode == 0:
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                return {"status": "ok", "output": r.stdout[:500]}
        return {"status": "error", "output": r.stdout[:500], "error": r.stderr[:300]}
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def send_telegram_report(session_type: str, snapshot: dict, commitments: dict,
                         task_queue: dict, triage: dict):
    """Send a summary report to Telegram via telegram_bridge."""
    try:
        from telegram_bridge import send_telegram
    except ImportError:
        log("telegram_bridge not available, skipping report")
        return

    lines = [
        f"🤖 **Autonomous Work Session — {session_type.title()}**",
        f"",
        f"📋 **Health Snapshot**:",
        f"  • Docker: {snapshot.get('docker_total', 0)} containers, {snapshot.get('docker_unhealthy', 0)} unhealthy",
        f"  • RAM: {snapshot.get('ram_total', '?')} total, {snapshot.get('ram_used', '?')} used",
        f"  • Disk: {snapshot.get('disk_pct', '?')}% used",
        f"  • Gateway: {snapshot.get('gateway', '?')} (hop {snapshot.get('hop', '?')})",
        f"",
        f"📝 **Commitments**: {commitments.get('output', 'no data')[:200]}",
        f"",
        f"📋 **Task Queue**: {task_queue.get('count', 0)} items",
    ]

    if task_queue.get("items"):
        for item in task_queue["items"][:3]:
            lines.append(f"  • {item[:80]}")

    ti = triage.get("summary", "")
    fixed = triage.get("auto_fixed", 0)
    human = triage.get("needs_human", 0)
    lines.append(f"")
    lines.append(f"🛠️ **Homelab Triage**: {fixed} auto-fixed, {human} need attention")

    if triage.get("status") == "error":
        lines.append(f"  ⚠️ Triage issue: {triage.get('error', '')[:100]}")

    text = "\n".join(lines)

    result = send_telegram(text, category="briefing", dedup_window=300)
    log(f"Telegram report: {result.get('status', 'unknown')}")


def run_session(session_type: str):
    log(f"{'='*60}")
    log(f"Work Session: {session_type}")
    log(f"{'='*60}")

    snapshot = health_snapshot()
    log(f"Health: docker={snapshot['docker_total']} containers, {snapshot['docker_unhealthy']} unhealthy")
    log(f"Disk: {snapshot.get('disk_pct', '?')}%, Gateway: {snapshot.get('gateway', '?')}")

    commitments = commitment_check()
    if commitments.get("output"):
        log(f"Commitment status: {commitments['output'][:200]}")

    task_queue = task_queue_review()
    log(f"Task queue: {task_queue.get('count', 0)} items")

    triage = run_homelab_triage()
    log(f"Triage: {json.dumps(triage, default=str)[:200]}")

    send_telegram_report(session_type, snapshot, commitments, task_queue, triage)

    log(f"Session complete")


def main():
    if "--health-only" in sys.argv:
        snapshot = health_snapshot()
        print(json.dumps(snapshot, indent=2))
    elif "--type" in sys.argv:
        idx = sys.argv.index("--type")
        if idx + 1 < len(sys.argv):
            run_session(sys.argv[idx + 1])
        else:
            run_session("manual")
    else:
        run_session("manual")


if __name__ == "__main__":
    main()
