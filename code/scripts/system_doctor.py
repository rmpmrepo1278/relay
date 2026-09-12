#!/usr/bin/env python3
"""system_doctor.py — Self-healing maintenance.

Runs every 30 minutes via scheduler. Handles:
  - SQLite auto-vacuum (once daily)
  - Process health -> restart dead daemons
  - Orphaned semaphores/locks cleanup
  - Telegram 409 error handling

Disk cleanup is delegated to n8n Storage Watchdog.
Docker cleanup is delegated to n8n Nightly Docker Cleanup.
Container restart is delegated to n8n Container Auto-Heal.
"""

import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path.home() / ".hermes"
LOG = HERMES / "logs" / "system_doctor.log"
STATE = HERMES / "state" / "doctor_state.json"


def log(msg: str):
    ts = datetime.now().isoformat()
    entry = f"[{ts}] {msg}"
    print(entry)
    with open(LOG, "a") as f:
        f.write(entry + "\n")


def send_alert(text: str):
    try:
        import sys
        sys.path.insert(0, str(HERMES / "scripts"))
        from telegram_bridge import send_telegram
        send_telegram(text[:4096])
    except Exception as e:
        log(f"send_alert failed: {e}")


def load_state():
    try:
        if STATE.exists():
            return json.loads(STATE.read_text())
    except Exception as e:
        log(f"load_state failed: {e}")
    return {}


def save_state(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2))


def vacuum_dbs():
    state = load_state()
    last_vacuum = state.get("last_vacuum", "")
    if last_vacuum:
        try:
            last = datetime.fromisoformat(last_vacuum)
            if datetime.now() - last < timedelta(hours=24):
                return []
        except Exception:
            pass

    actions = []
    for db_path in Path.home().glob(".hermes/**/*.db"):
        if ".git" in str(db_path):
            continue
        try:
            size_before = db_path.stat().st_size
            conn = sqlite3.connect(str(db_path))
            conn.execute("VACUUM")
            conn.close()
            size_after = db_path.stat().st_size
            if size_before - size_after > 1024:
                actions.append(f"Vacuumed {db_path.name}: {size_before//1024}K -> {size_after//1024}K")
        except Exception as e:
            log(f"vacuum failed for {db_path.name}: {e}")

    state["last_vacuum"] = datetime.now().isoformat()
    save_state(state)
    return actions


def _dedup_alert(state, key, text, cooldown_hours=6):
    last = state.get("last_alert", {}).get(key, "")
    if last:
        try:
            last_ts = datetime.fromisoformat(last)
            if datetime.now() - last_ts < timedelta(hours=cooldown_hours):
                log(f"alert '{key}' suppressed (sent {last_ts.isoformat()})")
                return False
        except Exception:
            pass
    state.setdefault("last_alert", {})[key] = datetime.now().isoformat()
    send_alert(text)
    return True


def _gateway_health():
    try:
        r = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", "hermes"],
            capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception as e:
        log(f"gateway health check error: {e}")
        return "unknown"


def _gateway_service_name():
    try:
        r = subprocess.run(
            ["docker", "exec", "hermes", "sh", "-c", "ls /run/service"],
            capture_output=True, text=True, timeout=10)
        for name in r.stdout.split():
            if name.startswith("gateway"):
                return f"/run/service/{name}"
    except Exception as e:
        log(f"gateway service discovery error: {e}")
    return "/run/service/gateway-default"


def _restart_gateway_service(service):
    try:
        r = subprocess.run(
            ["docker", "exec", "-u", "root", "hermes", "/command/s6-svc", "-r", service],
            capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except Exception as e:
        log(f"gateway service restart error: {e}")
        return False


def check_processes():
    critical = {
        "hermes_scheduler": "hermes_scheduler.py.*--daemon",
        "docker_daemon": "dockerd",
    }
    state = load_state()
    actions = []
    for name, pattern in critical.items():
        try:
            r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5)
            if not r.stdout.strip():
                log(f"CRITICAL: {name} not running -- attempting restart")
                if name == "hermes_scheduler":
                    subprocess.Popen(
                        f"nohup python3 {HERMES / 'scripts' / 'hermes_scheduler.py'} --daemon > {HERMES / 'logs' / 'scheduler.log'} 2>&1 &",
                        shell=True,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    _dedup_alert(state, "hermes_scheduler_restarted",
                                 "Restarted hermes_scheduler after detecting it was down", cooldown_hours=1)
                    actions.append("Restarted hermes_scheduler")
        except Exception as e:
            log(f"process check error for {name}: {e}")

    gateway = _gateway_health()
    svc = _gateway_service_name()
    if gateway == "true":
        service = subprocess.run(
            ["docker", "exec", "hermes", "/command/s6-svstat", svc],
            capture_output=True, text=True, timeout=10)
        if service.stdout.strip() and "up" in service.stdout.lower() and "paused" not in service.stdout.lower():
            log(f"hermes container up; gateway service {svc}: {service.stdout.strip()[:60]}")
        else:
            log(f"hermes container up but gateway service {svc} down: {service.stdout.strip()[:80]}")
            if _restart_gateway_service(svc):
                _dedup_alert(state, "gateway_restarted",
                             "Restarted hermes_gateway (s6 service) after detecting it was down", cooldown_hours=1)
                actions.append("Restarted hermes_gateway (s6 service)")
    elif gateway == "false":
        _dedup_alert(state, "hermes_container_down",
                     "CRITICAL: hermes container is NOT running (gateway unreachable). Not auto-starting to avoid ownership side effects.")
        actions.append("hermes container down — gateway unreachable")
    else:
        log(f"gateway health unknown: {gateway}")

    save_state(state)
    return actions


def handle_telegram_409():
    actions = []
    backoff_file = HERMES / "state" / "telegram_backoff.json"
    tb_log = HERMES / "logs" / "telegram_bot.log"
    state = json.loads(backoff_file.read_text()) if backoff_file.exists() else {}
    last_offset = state.get("log_offset", 0)
    try:
        if tb_log.exists():
            size = tb_log.stat().st_size
            if size < last_offset:
                last_offset = 0
            if size > last_offset:
                with open(tb_log, "rb") as f:
                    f.seek(last_offset)
                    new_data = f.read().decode(errors="ignore")
                if "HTTP Error 409" in new_data:
                    state["consecutive_errors"] = state.get("consecutive_errors", 0) + 1
                    actions.append(f"Telegram 409 conflict detected ({state['consecutive_errors']} active)")
                elif state.get("consecutive_errors", 0) != 0:
                    state["consecutive_errors"] = 0
                    actions.append("Telegram 409 conflict resolved")
                state["log_offset"] = size
            backoff_file.write_text(json.dumps(state))
    except Exception:
        pass
    return actions


def clean_orphaned_locks():
    actions = []
    for lock_file in HERMES.rglob("*.lock"):
        lock_name = lock_file.stem.replace(".lock", "")
        try:
            r = subprocess.run(["pgrep", "-f", lock_name], capture_output=True, text=True, timeout=5)
            if not r.stdout.strip():
                lock_file.unlink()
                actions.append(f"Removed stale lock: {lock_file.name}")
        except Exception as e:
            log(f"lock check failed for {lock_file.name}: {e}")
    return actions


def doctor():
    log("=== System Doctor Run ===")
    all_actions = []
    all_actions.extend(vacuum_dbs())
    all_actions.extend(check_processes())
    all_actions.extend(handle_telegram_409())
    all_actions.extend(clean_orphaned_locks())
    all_actions.extend(check_graph_health())

    if all_actions:
        msg = "Doctor rundown:\n" + "\n".join(f"  - {a}" for a in all_actions)
        log(msg)
    else:
        log("All clear -- no issues found")

    return all_actions


def check_graph_health():
    try:
        import homelab_graph as hg
        stale = hg.crg_graph_health(stale_hours=48)
        out = []
        for s in stale:
            out.append("Graph stale/empty: {a} ({n} nodes, {d})".format(
                a=s.get("alias"), n=s.get("nodes", 0), d=s.get("last_updated")))
        return out
    except Exception:
        return []


def _last_notified_fingerprint() -> str:
    state = load_state() or {}
    return state.get("last_notified_fp", "")


def _save_notified_fingerprint(fp: str):
    state = load_state() or {}
    state["last_notified_fp"] = fp
    save_state(state)


if __name__ == "__main__":
    actions = doctor()
    ROUTINE_PREFIXES = (
        "Vacuumed",
        "Removed stale lock:",
    )
    noteworthy = [a for a in actions if not a.startswith(ROUTINE_PREFIXES)]
    # Dedup: only alert when the set of notable findings CHANGED since the last
    # run. Ongoing conditions (e.g. a long-stale CRG graph) are reported once and
    # stay silent until they resolve, change, or a new finding appears. This
    # prevents the same doctor: message from spamming every 30 minutes.
    sorted_notes = sorted(noteworthy)
    fingerprint = "\n".join(sorted_notes)
    if noteworthy and fingerprint != _last_notified_fingerprint():
        send_alert("doctor:\n" + "\n".join(f"  - {a}" for a in noteworthy))
        _save_notified_fingerprint(fingerprint)
    elif not noteworthy and _last_notified_fingerprint():
        # All-clear after a previous alert — reset so a future new issue re-alerts.
        _save_notified_fingerprint("")
