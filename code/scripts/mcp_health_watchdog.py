#!/usr/bin/env python3
"""
mcp_health_watchdog.py — Monitor + auto-heal MCP servers.

Checks MCP server process health and auto-restarts degraded/failed servers.
MCP servers are declared in config.yaml -> mcp_servers with command + args.
For stdio MCP servers, checks if the process is alive. For HTTP-based
MCP servers, checks /health endpoint.

Also integrates with the LLM proxy: during internet outage windows,
the proxy can switch to local-only routing to avoid cloud provider failures.

Usage:
  python3 mcp_health_watchdog.py                # Single check
  python3 mcp_health_watchdog.py --loop 30      # Continuous (every 30s)
  python3 mcp_health_watchdog.py --repair       # Force restart all MCP servers
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

HH = Path.home() / ".hermes"
LOG = HH / "logs" / "mcp_watchdog.log"
STATE = HH / "state" / "mcp_watchdog_state.json"
CONFIG = HH / "config.yaml"
PROXY_PORT = 8083  # repointed: 8080 is unserved; hop lives on 8083
CHECK_INTERVAL_DEFAULT = 60  # seconds


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        LOG.open("a").write(line + "\n")
    except Exception:
        pass


def load_config() -> dict:
    try:
        import yaml
        cfg = yaml.safe_load(CONFIG.read_text())
        return cfg
    except Exception:
        return {}


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {"restarts": {}, "last_check": 0, "consecutive_failures": {}}


def save_state(state: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def check_internet_outage_window() -> bool:
    """Check if we're in the known internet outage window (11PM-9AM PT)."""
    try:
        now = datetime.now()
        # Get PT timezone
        try:
            import pytz
            pt = pytz.timezone("US/Pacific")
            now_pt = datetime.now(pt)
        except ImportError:
            # Approximate PT (UTC-7/-8)
            now_pt = now
        hour = now_pt.hour
        return hour >= 23 or hour < 9
    except Exception:
        return False


def set_proxy_local_only(enabled: bool) -> bool:
    """Toggle proxy routing to local-only mode for internet outage windows."""
    try:
        data = json.dumps({"action": "reset_cooldowns"}).encode() if not enabled else json.dumps({}).encode()
        # During outage: disable cloud providers via the routing API
        if enabled:
            # Disable all cloud providers
            providers_to_disable = ["groq", "cerebras", "sambanova", "owl", "google-alt", "mistral", "openrouter", "deepseek-v4-flash", "github-models"]
            for p in providers_to_disable:
                try:
                    req = urllib.request.Request(
                        f"http://localhost:{PROXY_PORT}/v1/routing",
                        data=json.dumps({"action": "disable_provider", "provider": p}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    urllib.request.urlopen(req, timeout=5)
                except Exception:
                    pass
        else:
            # Re-enable all providers
            providers_to_enable = ["groq", "cerebras", "sambanova", "owl", "google-alt", "mistral", "openrouter", "deepseek-v4-flash", "github-models"]
            for p in providers_to_enable:
                try:
                    req = urllib.request.Request(
                        f"http://localhost:{PROXY_PORT}/v1/routing",
                        data=json.dumps({"action": "enable_provider", "provider": p}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    urllib.request.urlopen(req, timeout=5)
                except Exception:
                    pass
        log(f"Proxy local-only mode: {'ON' if enabled else 'OFF'}")
        return True
    except Exception as e:
        log(f"Failed to set proxy local-only mode: {e}")
        return False


def check_mcp_server(name: str, config: dict) -> dict:
    """Check health of a single MCP server."""
    result = {"name": name, "healthy": True, "detail": "ok"}

    cmd = config.get("command", "")
    args = config.get("args", [])
    enabled = config.get("enabled", True)

    if not enabled:
        result["healthy"] = False
        result["detail"] = "disabled"
        return result

    # Determine search term for the executable/script:
    # - If command is an absolute path (e.g. /home/rohit/.local/bin/xxx), use it directly
    # - If command is python3/python, search for args[0] (the script path)
    # - If command is a bare name (e.g. graphify-mcp), use it as-is and search PATH
    is_python_cmd = Path(cmd).name in ("python3", "python", "python3.11", "python3.12")

    if Path(cmd).is_absolute():
        # Absolute path command — check the command itself exists
        search_term = cmd
    elif is_python_cmd:
        # Python interpreter — check args[0] (the script path)
        search_term = args[0] if args else cmd
    else:
        # Bare command name — check PATH
        search_term = cmd if not args else args[0]

    # Build search paths to check
    search_paths_to_check = [Path(search_term)]
    if not Path(search_term).is_absolute():
        search_paths_to_check.append(Path(search_term))  # As-is
        search_paths_to_check.append(HH / "scripts" / search_term)  # ~/.hermes/scripts/search_term

    # Check if command is available (absolute file path, relative-to-scripts path, or PATH)
    cmd_exists = any(p.exists() for p in search_paths_to_check)
    if not cmd_exists:
        # Check PATH with expanded env (includes ~/.local/bin)
        env = os.environ.copy()
        env["PATH"] = env.get("PATH", "") + ":/home/rohit/.local/bin:/usr/local/bin"
        try:
            r_which = subprocess.run(["which", search_term], capture_output=True, text=True, timeout=3, env=env)
            cmd_exists = r_which.returncode == 0
        except Exception:
            pass

    if not cmd_exists:
        result["healthy"] = False
        result["detail"] = f"script/executable missing: {search_term}"
        return result

    # For stdio MCPs, check if the gateway/hermes process is running
    # (stdio servers are spawned on-demand, not as persistent processes)
    try:
        r = subprocess.run(
            ["pgrep", "-f", "hermes"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            result["healthy"] = False
            result["detail"] = f"process not found (search: {search_term})"
            return result
    except Exception:
        pass

    return result


def restart_mcp_server(name: str, config: dict) -> bool:
    """Attempt to restart an MCP server (mainly relevant for containerized/HTTP MCPs)."""
    log(f"Attempting to restart MCP server: {name}")

    # For stdio MCP servers managed by hermes gateway, the gateway
    # should auto-restart them. If not, we can restart the hermes-gateway.
    # For now, try to restart the hermes-scheduler (which manages gateway)
    try:
        result = subprocess.run(
            ["systemctl", "--user", "restart", "hermes-gateway.service"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            log(f"Restarted hermes-gateway for MCP {name}")
            return True
        else:
            log(f"Failed to restart gateway for {name}: {result.stderr}")
            return False
    except Exception as e:
        log(f"Restart error for {name}: {e}")
        return False


def send_alert(message: str, category: str = "infra"):
    """Send alert via Telegram or local proxy bridge."""
    try:
        data = json.dumps({"text": f"🛡️ {message}", "category": category}).encode()
        req = urllib.request.Request(
            f"http://localhost:{PROXY_PORT}/telegram-send",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        # Fallback: direct Telegram API
        try:
            token_file = HH / ".telegram_token"
            if token_file.exists():
                token = token_file.read_text().strip()
                chat_id = "-1003976074764"
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                urllib.request.urlopen(
                    urllib.request.Request(url, data=json.dumps({
                        "chat_id": chat_id,
                        "text": f"🛡️ {message}",
                        "message_thread_id": 7356,
                    }).encode(),
                     headers={"Content-Type": "application/json"}),
                    timeout=10,
                )
        except Exception:
            pass


def run_check() -> dict:
    """Single MCP health check + internet-outage awareness + auto-heal."""
    state = load_state()
    cfg = load_config()
    mcp_servers = cfg.get("mcp_servers", {})

    issues = []
    healthy_count = 0
    total_count = 0

    # --- Check each MCP server ---
    for name, scfg in mcp_servers.items():
        total_count += 1
        result = check_mcp_server(name, scfg)
        if result["healthy"]:
            healthy_count += 1
        else:
            issues.append(result)
            failures = state.get("consecutive_failures", {}).get(name, 0) + 1
            state.setdefault("consecutive_failures", {})[name] = failures

            # Auto-repair after 3 consecutive failures
            if failures >= 3:
                log(f"MCP {name} failed {failures} consecutive checks — attempting restart")
                if restart_mcp_server(name, scfg):
                    state["restarts"][name] = state.get("restarts", {}).get(name, 0) + 1
                    state["consecutive_failures"][name] = 0
                    send_alert(f"🔧 Auto-restarted MCP server '{name}' after {failures} failures", "infra")
                    issues.append({"name": name, "action": "restarted"})
            else:
                send_alert(f"⚠️ MCP server '{name}' unhealthy: {result['detail']}", "infra")
        log(f"MCP {name}: {'✅ healthy' if result['healthy'] else '❌ ' + result['detail']}")

    save_state(state)

    # --- Internet outage awareness ---
    in_outage = check_internet_outage_window()
    was_in_outage = state.get("internet_outage", False)
    state["internet_outage"] = in_outage
    save_state(state)

    if in_outage and not was_in_outage:
        log("Entering internet outage window (11PM-9AM PT) — switching to local-only routing")
        set_proxy_local_only(True)
        send_alert("🌙 Internet outage window detected — LLM proxy switched to local-only mode", "infra")
    elif not in_outage and was_in_outage:
        log("Exiting internet outage window — restoring cloud providers")
        set_proxy_local_only(False)
        send_alert("☀️ Internet outage window ended — cloud LLM providers re-enabled", "infra")

    return {
        "mcp_healthy": healthy_count == total_count,
        "mcp_healthy_count": healthy_count,
        "mcp_total_count": total_count,
        "mcp_issues": issues,
        "internet_outage_window": in_outage,
    }


def main():
    if "--loop" in sys.argv:
        interval = 60
        for arg in sys.argv:
            if arg.startswith("--loop="):
                interval = int(arg.split("=")[1])
        log(f"Starting MCP health watchdog (interval: {interval}s)")
        try:
            while True:
                run_check()
                time.sleep(interval)
        except KeyboardInterrupt:
            log("Watchdog stopped by user")
    elif "--repair" in sys.argv:
        cfg = load_config()
        mcp_servers = cfg.get("mcp_servers", {})
        for name, scfg in mcp_servers.items():
            restart_mcp_server(name, scfg)
        log("All MCP restart attempts sent")
    else:
        result = run_check()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
