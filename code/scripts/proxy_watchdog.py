#!/usr/bin/env python3
"""
proxy_watchdog.py — Health monitor + auto-heal for the LLM front door (tokenjuice-hop, port 8083).

Runs as a daemon or single-shot. Monitors:
  1. Proxy process health (curl /health)
  2. Provider circuit-breaker states (curl /v1/status)
  3. Provider daily-limit usage vs config.yaml limits
  4. Provider response time health probing

Auto-heals:
  - Restart front door if /health is down (systemctl restart)
  - Reset circuit breakers when ALL providers are tripped
  - Disable providers that hit daily limit
  - Re-enable providers after daily reset (midnight UTC)
  - Detect "port up but generation empty" via an actual completion probe
    (auto/best-chat), then auto-restart hop, then magnitude (2026-09-11).
    Plain `systemctl restart tokenjuice-hop` can strand the unit deactivating,
    so restarts escalate to SIGKILL + start if the job hangs.

Alerts via Telegram when actions are taken.

Usage:
  python3 proxy_watchdog.py                # Single health check
  python3 proxy_watchdog.py --loop 30      # Loop every 30s
  python3 proxy_watchdog.py --restart      # Force restart proxy
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import urllib.request
import urllib.error

HH = Path.home() / ".hermes"
LOG = HH / "logs" / "proxy_watchdog.log"
STATE = HH / "state" / "proxy_watchdog_state.json"
CONFIG = HH / "config.yaml"
PROXY_PORT = 8083
PROXY_SERVICE = "tokenjuice-hop"
PROXY_TIMEOUT = 30  # seconds for health checks
# Model the probe exercises. Backed by magnitude (reliable); combo/pi-free-fallback
# is flaky and would false-positive the recovery path.
PROBE_MODEL = "auto/best-chat"


def _run(args: list[str], timeout: int = 20) -> bool:
    try:
        subprocess.run(args, capture_output=True, timeout=timeout)
        return True
    except Exception as e:
        log(f"command failed/timed out: {' '.join(args[:4])}... ({e})")
        return False


def restart_service(unit: str, user_unit: bool = False) -> bool:
    """Restart a unit; if the job hangs, SIGKILL leftovers then start fresh."""
    pre = ["systemctl", "--user"] if user_unit else ["sudo", "-n", "systemctl"]
    if _run(pre + ["restart", unit]):
        return True
    log(f"Restart of {unit} hung — escalating to SIGKILL + start")
    _run(pre + ["kill", "--signal=SIGKILL", unit])
    _run(pre + ["reset-failed", unit])
    return _run(pre + ["start", unit])


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        with LOG.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {"last_restart": 0, "daily_reset_date": "", "circuit_resets": 0, "restarts": 0,
            "consecutive_empty": 0, "last_empty_recovery": 0, "empty_recoveries": 0}


def save_state(state: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def load_config() -> dict:
    try:
        import yaml
        cfg = yaml.safe_load(CONFIG.read_text())
        return cfg.get("proxy", {})
    except Exception:
        return {}


def health_check(timeout: int = PROXY_TIMEOUT) -> tuple[bool, str]:
    """Check proxy /health endpoint."""
    try:
        req = urllib.request.Request(f"http://localhost:{PROXY_PORT}/health")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            if data.get("status") == "ok":
                return True, data.get("type", "proxy")
            return False, f"unhealthy: {data}"
    except urllib.error.URLError as e:
        return False, f"connection failed: {e.reason}"
    except Exception as e:
        return False, f"error: {e}"


def status_check(timeout: int = PROXY_TIMEOUT) -> dict | None:
    """Get proxy status.

    Tries hop's /v1/status first (rich per-provider health data). hop
    (tokenjuice-hop) does not serve /v1/status; when it is absent, fall
    back to /v1/token-juice + /v1/models so provider tracking stays alive
    instead of silently degrading to a bare ping.
    """
    try:
        req = urllib.request.Request(f"http://localhost:{PROXY_PORT}/v1/status")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        pass
    # Fallback: synthesize status from the endpoints hop actually serves.
    try:
        ju = None
        try:
            jreq = urllib.request.Request(f"http://localhost:{PROXY_PORT}/v1/token-juice")
            with urllib.request.urlopen(jreq, timeout=timeout) as jresp:
                ju = json.loads(jresp.read())
        except Exception:
            pass
        mreq = urllib.request.Request(f"http://localhost:{PROXY_PORT}/v1/models")
        with urllib.request.urlopen(mreq, timeout=timeout) as mresp:
            models = json.loads(mresp.read()).get("data", [])
        return {"providers": {}, "models_available": len(models),
                "token_juice": ju or {}}
    except Exception:
        return None


def restart_proxy() -> bool:
    """Restart the LLM front door via systemd."""
    state = load_state()
    now = time.time()

    # Avoid restart loops. The timestamp is written on ATTEMPT, not only on
    # success, so a failed recovery still rate-limits the next restart.
    if now - state.get("last_restart", 0) < 120:
        log("Restart skipped: last restart was <120s ago (rate-limited)")
        return False
    state["last_restart"] = now
    save_state(state)

    log("Attempting to restart LLM proxy server...")
    if not restart_service(PROXY_SERVICE):
        log("Systemctl restart + escalation failed for LLM proxy")
        return False

    # Wait for health check
    for i in range(15):
        time.sleep(2)
        ok, msg = health_check(timeout=5)
        if ok:
            log(f"Proxy recovered after restart ({PROXY_SERVICE})")
            state["restarts"] = state.get("restarts", 0) + 1
            state["consecutive_down"] = 0
            save_state(state)
            return True
    log("Proxy did not become healthy after 30s")
    return False


def generation_probe(timeout: int = 60) -> tuple[bool, str]:
    """Actually generate a token through hop; True only on non-empty content.

    Guards the 'port is up but every model returns empty' failure mode, which
    /health alone cannot see.
    """
    body = json.dumps({
        "model": PROBE_MODEL,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 64,
    }).encode()
    req = urllib.request.Request(
        f"http://localhost:{PROXY_PORT}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        message = (((data.get("choices") or [{}])[0].get("message") or {}))
        content = (message.get("content") or "").strip()
        reasoning = (message.get("reasoning_content") or "").strip()
        if content or reasoning:
            return True, data.get("model", "?")
        return False, "empty content"
    except Exception as e:
        return False, f"probe failed: {e}"


def recover_generation() -> bool:
    """Self-heal when hop is up but generates nothing: restart hop, then magnitude."""
    state = load_state()
    now = time.time()
    if now - state.get("last_empty_recovery", 0) < 180:
        log("Empty-recovery skipped: <180s since last attempt (rate-limited)")
        return False
    state["last_empty_recovery"] = now
    save_state(state)
    log("Generation returning empty content — restarting hop, then magnitude if needed")
    restart_service(PROXY_SERVICE)
    time.sleep(6)
    ok, detail = generation_probe(timeout=90)
    if ok:
        log(f"Recovered after hop restart: {detail}")
        state["empty_recoveries"] = state.get("empty_recoveries", 0) + 1
        state["consecutive_empty"] = 0
        save_state(state)
        send_alert(f"🔄 LLM generation was empty; hop restart recovered it ({detail})", "infra")
        return True
    log(f"Hop restart did not fix empty generation ({detail}) — restarting magnitude")
    restart_service("magnitude.service", user_unit=True)
    time.sleep(20)
    ok, detail = generation_probe(timeout=90)
    if ok:
        log(f"Recovered after magnitude restart: {detail}")
        state["empty_recoveries"] = state.get("empty_recoveries", 0) + 1
        state["consecutive_empty"] = 0
        save_state(state)
        send_alert(f"🔄 LLM generation recovered after magnitude restart ({detail})", "infra")
        return True
    log(f"Magnitude restart did not fix empty generation ({detail})")
    send_alert("🔴 LLM generates empty responses; hop + magnitude restarts did not recover", "infra")
    return False


def reset_all_circuit_breakers() -> bool:
    """Reset all circuit breakers via the /v1/routing endpoint."""
    try:
        data = json.dumps({"action": "reset_circuit_breaker"}).encode()
        req = urllib.request.Request(
            f"http://localhost:{PROXY_PORT}/v1/routing",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            log(f"Circuit breakers reset: {result}")
            return result.get("success", False)
    except Exception as e:
        log(f"Failed to reset circuit breakers: {e}")
        return False


def check_providers() -> list[str]:
    """Check provider status and return list of issues found."""
    issues = []
    status = status_check()
    if status is None:
        return ["proxy unreachable"]

    providers = status.get("providers", {})
    if not providers:
        # hop (tokenjuice-hop) has no per-provider health; nothing to flag.
        return []
    config = load_config()
    config_providers = config.get("providers", {})

    all_tripped = True
    working_providers = 0
    daily_exhausted = []

    for name, pinfo in providers.items():
        cb = pinfo.get("circuit_breaker", {})
        cb_state = cb.get("state", "UNKNOWN")
        healthy = pinfo.get("health_probe", {}).get("healthy", False)
        enabled = pinfo.get("enabled", True)
        failures = cb.get("failures", 0)
        available = cb.get("available", True)

        if cb_state in ("CLOSED", "DEGRADED") and available:
            working_providers += 1
        if cb_state == "OPEN":
            if healthy and failures > 0:
                pass  # Tripped but was recently healthy — keep monitoring
            issues.append(f"{name}: circuit breaker OPEN ({failures} failures)")
        if not enabled:
            issues.append(f"{name}: disabled")

        # Check daily limits
        cfg_p = config_providers.get(name, {})
        daily_limit = cfg_p.get("daily_limit", 0)
        if daily_limit <= 0:
            continue

        # Read usage from state file
        usage_file = HH / "data" / "provider_usage" / f"{name}.json"
        if usage_file.exists():
            try:
                usage = json.loads(usage_file.read_text())
                tokens_used = usage.get("tokens_today", 0)
                if tokens_used >= daily_limit * 0.95:
                    daily_exhausted.append(f"{name}: {tokens_used}/{daily_limit} (95%+)")
            except Exception:
                pass

    # If ALL providers are tripped, reset circuit breakers
    if working_providers == 0 and providers:
        log("⚠️ ALL providers tripped — resetting circuit breakers")
        reset_all_circuit_breakers()
        issues.append("circuit_reset_triggered")

    if daily_exhausted:
        issues.extend(daily_exhausted)

    return issues


def send_alert(message: str, category: str = "homelab"):
    """Send alert via Telegram bridge."""
    try:
        # Use the telegram bridge directly
        import httpx
        # Try direct HTTP POST to telegram-send endpoint
        url = "http://localhost:8082/telegram-send"
        payload = {
            "text": f"🛡️ {message}",
            "category": category,
            "priority": "normal",
        }
        # Try local bridge, fall back to direct bot API
        resp = httpx.post(url, json=payload, timeout=5)
        if resp.status_code == 200:
            return
    except Exception:
        pass

    # Fallback: direct Telegram API
    try:
        token_file = HH / ".telegram_token"
        if token_file.exists():
            token = token_file.read_text().strip()
            chat_id = "-1003976074764"  # Chaguli forum
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            urllib.request.urlopen(
                urllib.request.Request(url, data=json.dumps({
                    "chat_id": chat_id,
                    "text": f"🛡️ {message}",
                    "message_thread_id": 7356,  # infra topic
                }).encode(),
                 headers={"Content-Type": "application/json"}),
                timeout=10,
            )
    except Exception:
        pass


def run_check() -> dict:
    """Single health check + auto-heal cycle."""
    state = load_state()
    now = datetime.now(timezone.utc)

    # 1. Proxy health check
    ok, detail = health_check()
    if not ok:
        log(f"Proxy DOWN: {detail}")
        state["consecutive_down"] = state.get("consecutive_down", 0) + 1
        save_state(state)
        if state["consecutive_down"] < 2:
            log(f"Skipping restart: transient miss #{state['consecutive_down']} (need 2 consecutive)")
            return {"proxy_healthy": False, "restarted": False, "detail": detail}
        restored = restart_proxy()
        if restored:
            send_alert(f"🔄 LLM proxy restarted (was down: {detail})", "infra")
        else:
            send_alert(f"🔴 LLM proxy DOWN and restart failed ({detail})", "infra")
        return {"proxy_healthy": False, "restarted": restored, "detail": detail}

    if state.get("consecutive_down"):
        state["consecutive_down"] = 0
        save_state(state)
    issues = []

    # Generation probe: hop may answer /health but serve empty content.
    gen_ok, gen_detail = generation_probe()
    # Circuit-breaker telemetry: the generation probe exercises hop -> magnitude.
    try:
        from circuit_breaker import record_success, record_failure
        if gen_ok:
            record_success("magnitude")
        else:
            record_failure("magnitude", error=f"generation probe: {gen_detail}"[:120])
    except Exception:
        pass
    # Open-circuit alert: notify once per OPEN transition (persist last state).
    try:
        from circuit_breaker import get_all_circuits
        mag_state = next(
            (c.get("state") for c in get_all_circuits() if c.get("name") == "magnitude"),
            None)
        prev = state.get("magnitude_circuit_state")
        if mag_state == "OPEN" and prev != "OPEN":
            send_alert("🔴 magnitude circuit OPEN — generation probe failing persistently", "infra")
        if mag_state and mag_state != prev:
            state["magnitude_circuit_state"] = mag_state
            save_state(state)
    except Exception:
        pass
    if not gen_ok:
        state["consecutive_empty"] = state.get("consecutive_empty", 0) + 1
        save_state(state)
        if state["consecutive_empty"] < 2:
            log(f"Generation empty (transient miss #{state['consecutive_empty']}): {gen_detail}")
        else:
            recovered = recover_generation()
            log(f"Generation auto-recovery attempted; recovered={recovered} ({gen_detail})")
            if recovered:
                issues.append("generation_recovered")
        # Still report the issue but do not stop the rest of the cycle.
    else:
        if state.get("consecutive_empty"):
            state["consecutive_empty"] = 0
            save_state(state)
    log(f"Generation probe: {'ok' if gen_ok else 'EMPTY'} ({gen_detail})")

    legacy = status_check() is not None
    if legacy:
        date_str = now.strftime("%Y-%m-%d")
        if state.get("daily_reset_date") != date_str:
            log("Daily reset — re-enabling providers")
            try:
                data = json.dumps({"action": "reset_cooldowns"}).encode()
                req = urllib.request.Request(
                    f"http://localhost:{PROXY_PORT}/v1/routing",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=10)
            except Exception:
                pass
            state["daily_reset_date"] = date_str
            save_state(state)

        issues = check_providers()
        if issues:
            log(f"Provider issues: {issues}")
            for issue in issues:
                if "circuit_reset" in issue:
                    send_alert(f"⚠️ All LLM providers tripped — circuit breakers auto-reset", "infra")
                elif "daily_exhausted or" in issue or "%" in issue:
                    send_alert(f"📊 Provider near daily limit: {issue}", "infra")

        status = status_check()
        if status:
            providers = status.get("providers", {})
            if providers:
                healthy_count = sum(1 for p in providers.values()
                                  if p.get("health_probe", {}).get("healthy"))
                cb_closed = sum(1 for p in providers.values()
                               if p.get("circuit_breaker", {}).get("state") == "CLOSED")
                enabled_count = sum(1 for p in providers.values() if p.get("enabled"))
                log(f"Proxy healthy | providers: {healthy_count}/{len(providers)} healthy, "
                    f"{cb_closed} circuit_closed, {enabled_count} enabled")
            else:
                ju = status.get("token_juice", {})
                log(f"Proxy healthy | hop: {status.get('models_available', 0)} models, "
                    f"{ju.get('total_requests', 0)} requests, "
                    f"{ju.get('cache_misses', 0)} cache_miss, "
                    f"{ju.get('tokens_saved', 0)} tok_saved, "
                    f"{ju.get('errors', 0)} errors")

    save_state(state)
    return {
        "proxy_healthy": True,
        "provider_issues": issues,
        "detail": detail,
    }


def main():
    # Singleton guard: only one watchdog may run (a stray second instance was
    # the cause of the duplicated restart/alerts storm). Second instance exits.
    import fcntl
    _lock_path = HH / "state" / "proxy_watchdog.lock"
    _lock_path.parent.mkdir(parents=True, exist_ok=True)
    _lock_fd = open(_lock_path, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("proxy_watchdog already running (lock held) - exiting", file=sys.stderr)
        sys.exit(0)
    if "--restart" in sys.argv:
        ok = restart_proxy()
        sys.exit(0 if ok else 1)

    if any(a == "--loop" or a.startswith("--loop=") for a in sys.argv):
        interval = 30
        for arg in sys.argv:
            if arg.startswith("--loop=") and len(arg) > 7:
                interval = int(arg.split("=")[1])
        log(f"Starting proxy watchdog (loop interval: {interval}s)")
        try:
            while True:
                run_check()
                time.sleep(interval)
        except KeyboardInterrupt:
            log("Watchdog stopped by user")
    else:
        # Single check
        result = run_check()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
