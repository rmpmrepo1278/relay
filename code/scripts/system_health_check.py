#!/usr/bin/env python3
"""Unified health check for all homelab services. Reports failures via Telegram.

REGISTRY-DRIVEN: the list of what to monitor is DERIVED from the homelab
inventory (services/bin/inventory.py) — compose projects + enabled systemd
user units + homelab/meta.yml — never a hand-maintained list here.

Layers:
  - systemd units  : enabled, non-oneshot units must be active (auto-recover)
  - containers     : deployed containers must be running (alert only; n8n
                     Container Auto-Heal handles restarts)
  - meta services  : proc/telegram checks declared in homelab/meta.yml
"""
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path.home() / ".hermes" / "state"
SCRIPTS_DIR = Path.home() / ".hermes" / "scripts"
STATE_FILE = STATE_DIR / "system_health_state.json"
INVENTORY_FILE = Path("/home/rohit/services/inventory/inventory.json")
INVENTORY_BIN = Path("/home/rohit/services/bin")

# containers are monitored but NOT auto-restarted here (alert only); n8n's
# Container Auto-Heal owns container restarts. systemd units DO auto-recover.
AUTO_RESTART_DOCKER = False


def load_registry() -> list[dict]:
    """Service list from the inventory. Prefer the fresh generated file
    (inventory.timer regenerates every 5 min); fall back to a live build."""
    if INVENTORY_FILE.exists():
        try:
            return json.loads(INVENTORY_FILE.read_text()).get("services", [])
        except (json.JSONDecodeError, OSError) as e:
            print(f"inventory file read failed ({e}); trying live build")
    if INVENTORY_BIN.exists():
        try:
            sys.path.insert(0, str(INVENTORY_BIN))
            import inventory
            return inventory.build()
        except Exception as e:
            print(f"inventory module import failed: {e}")
    raise RuntimeError("no inventory available (module or file)")


def telegram_alert(message):
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from telegram_bridge import send_telegram
        send_telegram(f"⚠️ {message}")
    except Exception as e:
        print(f"Alert send failed: {e}")


def check_systemd(service_name):
    en = subprocess.run(["systemctl", "--user", "is-enabled", service_name], capture_output=True, text=True, timeout=10)
    if en.stdout.strip() in ("disabled", "static", "indirect"):
        return True
    r = subprocess.run(["systemctl", "--user", "is-active", service_name], capture_output=True, text=True, timeout=10)
    return r.stdout.strip() == "active"


def check_port(port, timeout=3):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        s.close()
        return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


def check_process(cmd_substr=None, pid_file=None):
    if pid_file:
        p = Path(pid_file)
        if p.exists():
            pid = p.read_text().strip()
            if pid and os.path.exists(f"/proc/{pid}"):
                return True
    if cmd_substr:
        r = subprocess.run(["pgrep", "-f", cmd_substr], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    return False


def check_telegram_gateway():
    gw_state = Path.home() / ".hermes" / "gateway_state.json"
    if not gw_state.exists():
        return False
    try:
        data = json.loads(gw_state.read_text())
        tg = data.get("platforms", {}).get("telegram", {})
        state = tg.get("state", "unknown")
        if tg.get("error_code"):
            return False
        return state == "connected"
    except (json.JSONDecodeError, OSError):
        return False


def running_container_names() -> set[str]:
    r = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=15)
    return set(r.stdout.split())


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"consecutive_failures": {}}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main():
    dry_run = "--dry-run" in sys.argv

    state = load_state()
    failures = []
    now = datetime.now(timezone.utc).isoformat()

    try:
        registry = load_registry()
    except RuntimeError as e:
        print(f"FATAL: {e}")
        sys.exit(2)

    known_keys = {e["id"] for e in registry}
    stale = set(state.get("consecutive_failures", {})) - known_keys
    for k in stale:
        del state["consecutive_failures"][k]
    if stale:
        print(f"pruned {len(stale)} stale state key(s): {', '.join(sorted(stale))}")

    running = running_container_names()

    for entry in registry:
        key = entry["id"]
        kind = entry.get("kind")
        # compose service name may differ from the actual container name
        check_name = entry.get("container_name") or entry.get("name")
        cfg = {"type": kind, "name": check_name, "cmd": entry.get("cmd"),
               "port": entry.get("port")}

        # systemd: enabled + non-oneshot units are expected running
        if kind == "systemd":
            if not entry.get("present") or entry.get("unit_type") == "oneshot":
                continue
            ok = check_systemd(cfg["name"] + ".service")
            recover = True
        # containers: deployed (incl. docker_run) are expected running
        elif kind == "container":
            if not entry.get("deployed"):
                continue
            ok = cfg["name"] in running
            recover = AUTO_RESTART_DOCKER
        # meta specials: proc / telegram declared in meta.yml
        elif kind == "proc":
            ok = check_process(cmd_substr=cfg.get("cmd"))
            if not ok and cfg.get("port"):
                ok = check_port(cfg["port"])
            recover = False
        elif kind == "telegram":
            ok = check_telegram_gateway()
            recover = False
        else:
            continue

        if ok:
            state.setdefault("consecutive_failures", {})[key] = 0
            continue

        prev = state.setdefault("consecutive_failures", {}).get(key, 0)
        state["consecutive_failures"][key] = prev + 1
        consec = prev + 1
        label = cfg.get("name") or key
        print(f"FAIL: {key} (failure #{consec})")

        if consec == 1:
            failures.append(label)

        if recover and not dry_run:
            subprocess.run(["systemctl", "--user", "reset-failed", cfg["name"] + ".service"],
                           capture_output=True, timeout=10)
            subprocess.run(["systemctl", "--user", "restart", cfg["name"] + ".service"],
                           capture_output=True, timeout=30)
            print(f"  -> restart issued for {cfg['name']}.service")

    if failures:
        msg = "System health failures detected:\n" + "\n".join(f"  • {f}" for f in failures)
        print(msg)
        if not dry_run:
            telegram_alert(msg)

    state["last_check"] = now
    state["last_failures"] = failures
    if not dry_run:
        save_state(state)

    if failures:
        sys.exit(1)

    print("All services healthy")
    sys.exit(0)


if __name__ == "__main__":
    main()
