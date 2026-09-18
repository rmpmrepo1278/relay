#!/usr/bin/env python3
"""Lightweight HTTP bridge for n8n — executes system commands and returns JSON."""
import html
import http.server
import json
import re
import subprocess
import urllib.parse
import urllib.request
import os
import signal
import sys
import time
import base64
import hashlib
from pathlib import Path
from datetime import datetime

PORT = 9199
THROTTLE_FILE = Path.home() / ".hermes" / "data" / "telegram_throttle.json"
CATEGORY_COOLDOWN = float(os.environ.get("TELEGRAM_CATEGORY_COOLDOWN", "300"))
BURST_LIMIT = int(os.environ.get("TELEGRAM_BURST_LIMIT", "10"))
BURST_WINDOW = float(os.environ.get("TELEGRAM_BURST_WINDOW", "60"))
THROTTLE_SUMMARY_INTERVAL = float(os.environ.get("TELEGRAM_SUMMARY_INTERVAL", "600"))
# Quiet General: every non-critical message that has no forum topic (i.e. would land in
# the default "General" topic) is re-bucketed into "general_digest" with a longer cooldown
# and sent at most once per GENERAL_COOLDOWN, so [tag]-prefixed / uncategorized traffic is
# batched into a single daily-ish alert instead of flooding General.
GENERAL_COOLDOWN = float(os.environ.get("TELEGRAM_GENERAL_COOLDOWN", "600"))
# Service auto-heal de-escalation: after HEAL_FAIL_THRESHOLD consecutive restart
# failures a unit is paused for HEAL_COOLDOWN seconds (no more hammering), and the
# automation is told to stop retrying until the pause expires.
HEAL_STATE_FILE = Path.home() / ".hermes" / "data" / "service_heal_state.json"
HEAL_FAIL_THRESHOLD = int(os.environ.get("SERVICE_HEAL_THRESHOLD", "3"))
HEAL_COOLDOWN = float(os.environ.get("SERVICE_HEAL_COOLDOWN", "3600"))
SCRIPTS_DIR = os.path.expanduser("~/.hermes/scripts")
HERMES_HOME = Path.home() / ".hermes"
_ENV_PATH = Path.home() / ".hermes" / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#"):
            continue
        if "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

AUTH_KEY = os.environ.get("BRIDGE_AUTH_KEY", "default-key-change-me")
SENSITIVE_PATHS = {
    "/run", "/cmd", "/docker-ps", "/docker-restart", "/docker-logs",
    "/docker-images", "/docker-unhealthy", "/docker-exec",
    "/service-restart", "/service-logs", "/service-heal-status", "/run-cron",
}
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_HOME_CHANNEL", "-1003976074764")

HANDLERS = {}
PROPOSAL_DIR = Path.home() / ".hermes" / "data" / "proposals"
PROPOSAL_DIR.mkdir(parents=True, exist_ok=True)

def handler(path):
    def decorator(f):
        HANDLERS[path] = f
        return f
    return decorator

@handler("/ping")
def handle_ping(data):
    return {"pong": True, "status": "ok"}

@handler("/system-health")
def handle_system_health(data):
    try:
        r = subprocess.run(
            ["sudo", "-u", "rohit", "env", "XDG_RUNTIME_DIR=/run/user/1000", "systemctl", "--user", "status", "hermes-gateway", "hermes-scheduler", "hermes-mind-loop"],
            capture_output=True, text=True, timeout=10
        )
        lines = r.stdout.split('\n')
        services = {}
        for s in ['hermes-gateway', 'hermes-scheduler', 'hermes-mind-loop']:
            for i, line in enumerate(lines):
                if s in line:
                    for j in range(i, min(i+10, len(lines))):
                        if 'Active:' in lines[j]:
                            services[s] = lines[j].strip()
                            break

        # System metrics
        import psutil
        load1, load5, load15 = psutil.getloadavg()
        mem = psutil.virtual_memory()
        # Dedup disk: only show unique filesystems (skip /home if same as /)
        seen_devs = set()
        disk_parts = []
        for p in psutil.disk_partitions(all=False):
            if p.device not in seen_devs:
                seen_devs.add(p.device)
                usage = psutil.disk_usage(p.mountpoint)
                disk_parts.append({
                    "mountpoint": p.mountpoint,
                    "device": p.device,
                    "total_gb": round(usage.total / (1024**3)),
                    "used_gb": round(usage.used / (1024**3)),
                    "free_gb": round(usage.free / (1024**3)),
                    "percent": usage.percent,
                })

        # Build digest text (n8n Format step passes this through directly)
        digest_lines = []
        digest_lines.append(f"Load: {load1:.1f} / {load5:.1f} / {load15:.1f}")
        digest_lines.append(f"Memory: {mem.used // (1024**2)}MB / {mem.total // (1024**2)}MB ({mem.percent}%)")
        for d in disk_parts:
            digest_lines.append(f"Disk {d['mountpoint']}: {d['percent']}% ({d['free_gb']}G free)")
        digest_lines.append("")
        digest_lines.append(f"Services ({len(services)} total):")
        for name, status in services.items():
            short = status.split(";")[0] if ";" in status else status
            digest_lines.append(f"  + {name} — {short}")

        # Container stats
        try:
            cr = subprocess.run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
                                capture_output=True, text=True, timeout=10)
            cnames = []
            unhealthy = []
            for line in cr.stdout.strip().split("\n"):
                if line:
                    parts = line.split("\t", 1)
                    cnames.append(parts[0])
                    if "unhealthy" in (parts[1] if len(parts) > 1 else "").lower():
                        unhealthy.append(parts[0])
            digest_lines.append("")
            digest_lines.append(f"Containers ({len(cnames)} total" + (f", {len(unhealthy)} unhealthy)" if unhealthy else "):"))
            for cn in sorted(cnames):
                marker = " ⚠" if cn in unhealthy else ""
                digest_lines.append(f"  + {cn}{marker}")
        except Exception:
            pass

        return {"status": "ok", "digest": "\n".join(digest_lines), "services": services,
                "load": {"1m": load1, "5m": load5, "15m": load15},
                "memory": {"total_gb": round(mem.total / (1024**3)), "used_gb": round(mem.used / (1024**3)), "percent": mem.percent},
                "disk": disk_parts}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- homelab-mcp client (stdlib urllib only) ---
MCP_URL = "http://127.0.0.1:9100/mcp"

def _mcp_sse_text(raw):
    out = []
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line.startswith("data:"):
            out.append(line[5:].strip())
    return "\n".join(out)

def mcp_call_tool(name, arguments=None, _id=1):
    """Call a homelab-mcp tool over Streamable HTTP using only stdlib urllib."""
    payload = {"jsonrpc": "2.0", "id": _id, "method": "initialize",
               "params": {"protocolVersion": "2024-11-05",
                          "capabilities": {"tools": {}},
                          "clientInfo": {"name": "n8n-bridge", "version": "1.0"}}}
    headers = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    def _post(body, session=None):
        h = dict(headers)
        if session:
            h["mcp-session-id"] = session
        req = urllib.request.Request(MCP_URL, data=json.dumps(body).encode(),
                                     headers=h, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            next_session = resp.headers.get("mcp-session-id") or session
            body_raw = resp.read()
            if not body_raw or b"data:" not in body_raw:
                return next_session, {}
            return next_session, json.loads(_mcp_sse_text(body_raw))
    session, _ = _post(payload)
    _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
    _, result = _post({"jsonrpc": "2.0", "id": _id + 1, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments or {}}}, session)
    if "error" in result:
        raise RuntimeError(result["error"].get("message"))
    texts = [c.get("text", "") for c in result.get("result", {}).get("content", []) if c.get("type") == "text"]
    return "\n".join(texts)


@handler("/docker-ps")
def handle_docker_ps(data):
    try:
        text = mcp_call_tool("list_all_hosts")
        containers = []
        for line in text.splitlines():
            line = line.strip()
            if not line or "(" not in line:
                continue
            if line.startswith("---") or line.startswith("Total") or line.startswith("=== "):
                continue
            raw_name, rest = line.split("(", 1)
            image = rest.rsplit(")", 1)[0].strip()
            name = raw_name.replace("\u2022", "").replace("\u2022", "").strip()
            containers.append({"name": name, "image": image})
        return {"status": "ok", "count": len(containers), "containers": containers}
    except Exception as e:
        return {"status": "error", "message": str(e)}

    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=10
        )
        containers = []
        for line in r.stdout.strip().split('\n'):
            if line:
                parts = line.split('\t', 2)
                containers.append({"name": parts[0], "status": parts[1] if len(parts)>1 else "", "ports": parts[2] if len(parts)>2 else ""})
        return {"status": "ok", "count": len(containers), "containers": containers}
    except Exception as e:
        return {"status": "error", "message": str(e)}

    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=10
        )
        containers = []
        for line in r.stdout.strip().split('\n'):
            if line:
                parts = line.split('\t', 2)
                containers.append({"name": parts[0], "status": parts[1] if len(parts)>1 else "", "ports": parts[2] if len(parts)>2 else ""})
        return {"status": "ok", "count": len(containers), "containers": containers}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@handler("/backup-status")
def handle_backup_status(data):
    report = "/opt/data/backup_all_report.json"
    if os.path.exists(report):
        with open(report) as f:
            return json.load(f)
    return {"status": "unknown", "message": "No backup report found"}

@handler("/disk-usage")
def handle_disk_usage(data):
    try:
        r = subprocess.run(["df", "-h", "/", "/home"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().split('\n')[1:]
        mounts = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 5:
                mounts.append({"filesystem": parts[0], "size": parts[1], "used": parts[2], "avail": parts[3], "use%": parts[4], "mounted": parts[5]})
        return {"status": "ok", "mounts": mounts}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@handler("/docker-restart")
def handle_docker_restart(data):
    name = data.get("container", "")
    if not name:
        return {"status": "error", "message": "container name required"}
    try:
        r = subprocess.run(["docker", "restart", name], capture_output=True, text=True, timeout=30)
        return ok_result(output=r.stdout.strip(), returncode=r.returncode, error=r.stderr.strip()) if r.returncode == 0 else err_result(r.stderr.strip())
    except Exception as e:
        return {"status": "error", "message": str(e)}

@handler("/docker-logs")
def handle_docker_logs(data):
    name = data.get("container", "")
    tail = data.get("tail", 50)
    if not name:
        return {"status": "error", "message": "container name required"}
    try:
        r = subprocess.run(["docker", "logs", "--tail", str(tail), name], capture_output=True, text=True, timeout=10)
        return {"status": "ok", "logs": r.stdout[-5000:] + r.stderr[-5000:]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@handler("/docker-exec")
def handle_docker_exec(data):
    name = data.get("container", "")
    cmd = data.get("cmd", "")
    if not name or not cmd:
        return {"status": "error", "message": "container and cmd required"}
    try:
        r = subprocess.run(["docker", "exec", name, "sh", "-c", cmd], capture_output=True, text=True, timeout=30)
        return ok_result(output=r.stdout[-5000:], stderr=r.stderr[-500:])
    except Exception as e:
        return {"status": "error", "message": str(e)}

def _heal_load_state():
    return _load_json(HEAL_STATE_FILE, {})


def _heal_save_state(state):
    _save_json(HEAL_STATE_FILE, state)


def _heal_notify_paused(name, st):
    """Send a single Telegram notice when auto-heal gives up on a unit."""
    try:
        _send_telegram_api(
            TELEGRAM_CHAT,
            f"\u23f8 Service Auto-Heal paused for {name}\n\n"
            f"{st['failures']} consecutive restart failures. Auto-heal won't retry "
            f"until {datetime.fromtimestamp(st['paused_until']).strftime('%H:%M')}. "
            f"- manual attention needed.",
            message_thread_id=None,
        )
    except Exception:
        pass


@handler("/service-restart")
def handle_service_restart(data):
    name = data.get("service", "")
    force = bool(data.get("force"))
    if not name:
        return {"status": "error", "service": name, "message": "service name required"}
    heal = _heal_load_state()
    st = heal.setdefault(name, {"failures": 0, "paused_until": 0, "last_error": ""})
    now = time.time()
    if not force and now < st.get("paused_until", 0):
        return {"status": "attention", "service": name, "paused": True,
                "consecutive_failures": st["failures"],
                "error": (f"auto-heal paused until {datetime.fromtimestamp(st['paused_until']).strftime('%H:%M')} "
                          f"after {st['failures']} consecutive failures")}
    try:
        show = subprocess.run(
            ["sudo", "-u", "rohit", "env", "XDG_RUNTIME_DIR=/run/user/1000", "systemctl", "--user", "show", name, "-p", "Type", "-p", "UnitFileState", "-p", "LoadState"],
            capture_output=True, text=True, timeout=10
        )
        props = {}
        for line in show.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v
        if props.get("LoadState") == "not-found":
            st["failures"] = st.get("failures", 0) + 1
            st["last_error"] = f"unit {name} not found"
            paused_now = st["failures"] >= HEAL_FAIL_THRESHOLD
            if paused_now:
                st["paused_until"] = now + HEAL_COOLDOWN
                _heal_save_state(heal)
                _heal_notify_paused(name, st)
            else:
                _heal_save_state(heal)
            return {"status": "attention" if paused_now else "error", "service": name,
                    "paused": paused_now, "consecutive_failures": st["failures"],
                    "error": f"unit {name} not found"}
        if props.get("Type") == "oneshot" or props.get("UnitFileState") == "static":
            reset = subprocess.run(
                ["sudo", "-u", "rohit", "env", "XDG_RUNTIME_DIR=/run/user/1000", "systemctl", "--user", "reset-failed", name],
                capture_output=True, text=True, timeout=10
            )
            st["failures"] = 0
            st["paused_until"] = 0
            _heal_save_state(heal)
            return {"status": "ok", "service": name, "skipped": True, "message": f"skipped non-restartable unit (Type={props.get('Type')}, UnitFileState={props.get('UnitFileState')}); reset-failed applied", "reset_output": reset.stdout.strip()}
        r = subprocess.run(
            ["sudo", "-u", "rohit", "env", "XDG_RUNTIME_DIR=/run/user/1000", "systemctl", "--user", "restart", name],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            st["failures"] = 0
            st["paused_until"] = 0
            st["last_error"] = ""
            _heal_save_state(heal)
            return ok_result(service=name, output=r.stdout.strip(), stderr=r.stderr.strip(), consecutive_failures=0)
        st["failures"] = st.get("failures", 0) + 1
        st["last_error"] = r.stderr.strip()
        paused_now = st["failures"] >= HEAL_FAIL_THRESHOLD
        if paused_now:
            st["paused_until"] = now + HEAL_COOLDOWN
        _heal_save_state(heal)
        if paused_now:
            _heal_notify_paused(name, st)
        return {"status": "attention" if paused_now else "error", "service": name,
                "paused": paused_now, "consecutive_failures": st["failures"],
                "output": r.stdout.strip(), "error": r.stderr.strip()}
    except Exception as e:
        return {"status": "error", "service": name, "message": str(e)}

@handler("/service-heal-status")
def handle_service_heal_status(data):
    """Return services currently paused by auto-heal de-escalation."""
    heal = _heal_load_state()
    now = time.time()
    paused = {
        name: {
            "until": datetime.fromtimestamp(st["paused_until"]).strftime("%H:%M"),
            "consecutive_failures": st.get("failures", 0),
        }
        for name, st in heal.items()
        if st.get("paused_until", 0) > now
    }
    return {"status": "ok", "paused": paused}


@handler("/service-logs")
def handle_service_logs(data):
    name = data.get("service", "")
    lines = data.get("lines", 50)
    if not name:
        return {"status": "error", "message": "service name required"}
    try:
        r = subprocess.run(
            ["sudo", "-u", "rohit", "env", "XDG_RUNTIME_DIR=/run/user/1000", "journalctl", "--user", "-u", name, "--no-pager", "-n", str(lines)],
            capture_output=True, text=True, timeout=10
        )
        return ok_result(logs=r.stdout[-5000:])
    except Exception as e:
        return {"status": "error", "message": str(e)}

@handler("/run")
def handle_run(data):
    cmd = data.get("cmd", "")
    timeout_sec = data.get("timeout", 30)
    if not cmd:
        return {"status": "error", "message": "cmd required"}
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout_sec)
        return ok_result(output=r.stdout[-5000:], stderr=r.stderr[-500:], returncode=r.returncode)
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "command timed out"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@handler("/health-ping")
def handle_health_ping(data):
    return {"ping": True, "status": "ok", "timestamp": time.time()}

@handler("/metrics")
def handle_metrics(data):
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        return {"status": "ok", "cpu_percent": cpu, "mem_used_mb": mem.used // 1024**2, "disk_avail_mb": mem.available // 1024**2}
    except:
        return {"status": "ok", "cpu_percent": 0, "mem_used_mb": 0, "disk_avail_mb": 0}

def _load_json(path, default=None):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default if default is not None else {}


def _save_json(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    except Exception:
        pass


def _message_category(text):
    t = (text or "").strip()
    m = re.match(r"^\[([A-Za-z0-9_\-\.]+)\]", t)
    if m:
        return m.group(1).lower()
    low = t.lower()
    if "is down" in low or "is offline" in low or "unreachable" in low:
        return "down"
    if t.startswith("doctor:"):
        return "doctor"
    if "auto-fix" in low or "autonomous fix" in low:
        return "auto_fix"
    if "briefing" in low:
        return "briefing"
    if "digest" in low or "inbox" in low:
        return "email"
    if "night report" in low:
        return "night_report"
    return "other"


def _send_telegram_api(chat_id, text, parse_mode="", message_thread_id=None):
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if message_thread_id is not None:
        payload["message_thread_id"] = int(message_thread_id)
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read())


def _topic_for_category(category):
    """Map a category to a forum topic (message_thread_id) via env.

    Env: TELEGRAM_TOPIC_<CATEGORY> (e.g. TELEGRAM_TOPIC_CAREER).
    Returns None when unset -> message lands in the chat's default topic.
    """
    if not category:
        return None
    return os.environ.get(f"TELEGRAM_TOPIC_{category.upper()}")


@handler("/telegram-send")
def handle_telegram_send(data):
    text = data.get("text", "")
    chat_id = data.get("chat_id", TELEGRAM_CHAT)
    parse_mode = data.get("parse_mode", "")
    if not text:
        return {"status": "error", "message": "text required"}

    # Commitment interceptor: scan outgoing messages for promise language
    # and auto-register commitments before delivery (mirrors gateway hook).
    try:
        sys.path.insert(0, SCRIPTS_DIR)
        from commitment_interceptor import scan_message as _scan_commitments
        _scan_result = _scan_commitments(text, source="telegram")
        if _scan_result.get("has_commitments"):
            import logging as _logging
            _logging.info("commitment_interceptor: registered %d commitment(s) via bridge /telegram-send", len(_scan_result["commitments"]))
    except Exception:
        pass

    # Global exact-match dedup: suppress identical text to same chat within window.
    dedup_file = Path.home() / ".hermes" / "data" / "telegram_dedup.json"
    window = float(data.get("dedup_window", 120))
    now = time.time()
    last_seen = _load_json(dedup_file, {})
    key = f"{chat_id}|{text}"
    last = last_seen.get(key)
    if last and (now - last) < window:
        return {"status": "ok", "deduped": True, "message": "duplicate suppressed"}
    last_seen[key] = now
    last_seen = {k: v for k, v in last_seen.items() if now - v < 3600}
    _save_json(dedup_file, last_seen)

    # Throttle: per-category cooldown + per-chat burst limit (critical bypasses).
    priority = data.get("priority", "normal")
    category = data.get("category") or _message_category(text)
    message_thread_id = data.get("message_thread_id") or _topic_for_category(category)
    critical = str(priority).lower() == "critical"
    # Quiet General: re-bucket all non-critical messages with no forum topic (General-bound)
    # into a single shared "general_digest" bucket with a longer cooldown, so [tag]-prefixed
    # or uncategorized traffic is batched into at most one General alert per GENERAL_COOLDOWN
    # instead of flooding General. critical and topic-mapped categories are unaffected.
    if not critical and message_thread_id is None:
        category = "general_digest"
    cd = GENERAL_COOLDOWN if category == "general_digest" else CATEGORY_COOLDOWN
    state = _load_json(THROTTLE_FILE, {})
    chat_state = state.setdefault(str(chat_id), {})
    chat_state["burst"] = [t for t in chat_state.get("burst", []) if now - t < BURST_WINDOW]
    cat_key = f"cat:{category}"
    cat_state = chat_state.setdefault(cat_key, {"suppressed": 0, "notified": 0})
    last_cat = cat_state.get("last", 0)
    if not critical and (len(chat_state["burst"]) >= BURST_LIMIT or (last_cat and (now - last_cat) < cd)):
        cat_state["suppressed"] = cat_state.get("suppressed", 0) + 1
        result = {"status": "ok", "throttled": True, "category": category}
        _save_json(THROTTLE_FILE, state)
        return result

    # Allowed: record burst + category timestamp, then send.
    chat_state["burst"].append(now)
    cat_state["last"] = now
    cat_state["suppressed"] = 0
    cat_state["notified"] = 0
    chat_state = {k: v for k, v in chat_state.items() if not (isinstance(v, dict) and v.get("last") and (now - v["last"]) > 3600)}
    chat_state["burst"] = [t for t in chat_state.get("burst", []) if now - t < BURST_WINDOW]
    state[str(chat_id)] = chat_state
    _save_json(THROTTLE_FILE, state)

    try:
        return {"status": "ok", "response": _send_telegram_api(chat_id, text, parse_mode, message_thread_id=message_thread_id)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── Proposal queue: /send <id> + /skip <id> for Telegram-confirm authoring ──

def _save_proposal(pid: str, proposal: dict) -> None:
    """Persist a pending proposal so /send or /skip can retrieve it."""
    f = PROPOSAL_DIR / f"{pid}.json"
    f.write_text(json.dumps(proposal, default=str, indent=2))


def _load_proposal(pid: str) -> dict | None:
    f = PROPOSAL_DIR / f"{pid}.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return None


def _clear_proposal(pid: str) -> None:
    f = PROPOSAL_DIR / f"{pid}.json"
    try:
        f.unlink(missing_ok=True)
    except Exception:
        pass


@handler("/propose")
def handle_propose(data):
    """
    Register a proposal for later /send or /skip confirmation.
    data = {action: send_email|create_event|send_telegram|run_command,
            content/summary/to/subject/start/command: ...,
            message_thread_id: int (optional), category: str (optional)}
    Returns {proposal_id, telegram_preview} so caller can surface to user.
    """
    import hashlib as _h
    pid = _h.sha256(f"{data.get('action','?')}:{data.get('content','?')}:{time.time()}".encode()).hexdigest()[:12]
    proposal = {
        "id": pid,
        "action": data.get("action", "send_telegram"),
        "created": datetime.now().isoformat(),
        "message_thread_id": data.get("message_thread_id"),
        "category": data.get("category"),
        "payload": {k: v for k, v in data.items() if k not in ("action", "message_thread_id", "category")},
    }
    _save_proposal(pid, proposal)

    # Generate the Telegram preview text with inline instructions
    action = proposal["action"]
    if action == "send_email":
        p = proposal["payload"]
        preview = f"📧 *Email draft → {p.get('to','?')}*\nSubject: {p.get('subject','')}\n\n{p.get('body','')[:200]}"
    elif action == "create_event":
        p = proposal["payload"]
        preview = f"📅 *Calendar event: {p.get('summary','')[:60]}*\nWhen: {p.get('start','')[:40]}"
    elif action == "run_command":
        p = proposal["payload"]
        preview = f"🛠️ *Proposed command:*\n```\n{p.get('command','')}\n```"
    else:
        p = proposal["payload"]
        preview = str(p.get("content", p.get("text", ""))[:300])

    preview += f"\n\n✅ `/send {pid}`  ❌ `/skip {pid}`"
    return {"status": "ok", "proposal_id": pid, "preview": preview}


@handler("/send")
def handle_send(data):
    """Execute a pending proposal (user confirmed via /send <id>)."""
    pid = (data.get("args") or "").strip()
    if not pid:
        pid = (data.get("text", "").split()[-1] if data.get("text") else "")
    if not pid:
        return {"text": "❌ Usage: /send <proposal_id>"}

    proposal = _load_proposal(pid)
    if not proposal:
        return {"text": f"❌ Proposal `{pid}` not found (already confirmed or expired)."}

    action = proposal["action"]
    payload = proposal["payload"]
    mtid = proposal.get("message_thread_id")
    category = proposal.get("category", "other")

    try:
        if action == "send_email":
            sys.path.insert(0, SCRIPTS_DIR)
            from email_intelligence import send_email
            try:
                result = send_email(
                    to=payload.get("to", ""),
                    subject=payload.get("subject", "Sent via Hermes"),
                    body=payload.get("body", ""),
                )
                text = f"✅ Email sent to `{payload.get('to','?')[:40]}`. Message ID: {result.get('id', '?')[:20]}."
            except Exception as api_err:
                if "invalid_scope" in str(api_err) or "insufficient" in str(api_err).lower():
                    text = (f"⚠️ OAuth scope insufficient. To send email, re-authenticate:\n"
                            f"```\ncd ~/.hermes/scripts && python3 email_intelligence.py --auth\n```\n"
                            f"This grants `gmail.send` + `gmail.compose` scopes.")
                else:
                    raise

        elif action == "create_event":
            sys.path.insert(0, SCRIPTS_DIR)
            from calendar_intelligence import create_event
            result = create_event(
                summary=payload.get("summary", ""),
                start_iso=payload.get("start", ""),
                end_iso=payload.get("end", ""),
                description=payload.get("description"),
                attendees=payload.get("attendees"),
            )
            text = f"✅ Calendar event created: [{result.get('htmlLink','').split('/')[-1] if result.get('htmlLink') else '✓'}]({result.get('htmlLink','')[:80]})"

        elif action == "run_command":
            cmd = payload.get("command", "")
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            text = f"✅ `/{cmd[:60]}`\n```\n{r.stdout[:300] if r.stdout else 'exit 0'}\n```" if r.returncode == 0 else f"❌ Command failed: `{r.stderr[:200]}`"

        elif action == "send_telegram":
            _send_telegram_api(
                TELEGRAM_CHAT, payload.get("content", ""),
                message_thread_id=mtid or _topic_for_category(category)
            )
            text = "✅ Message sent."

        else:
            text = f"❌ Unknown action: `{action}`"

        # Record outcome
        try:
            sys.path.insert(0, SCRIPTS_DIR)
            import narrative_memory as _nm
            _nm.store_episode({"type": "action", "content": f"Proposal {pid} confirmed: {action}", "metadata": {"proposal_id": pid, "action": action, "outcome": "sent"}})
        except Exception:
            pass

        _clear_proposal(pid)

    except Exception as e:
        text = f"❌ Proposal execution error: {e}"
        _clear_proposal(pid)

    return {"text": text}


@handler("/skip")
def handle_skip(data):
    """Discard a pending proposal (user rejected via /skip <id>)."""
    pid = (data.get("args") or "").strip()
    if not pid:
        pid = data.get("text", "").split()[-1] if data.get("text") else ""
    if not pid:
        return {"text": "❌ Usage: /skip <proposal_id>"}

    proposal = _load_proposal(pid)
    if not proposal:
        return {"text": f"❌ Proposal `{pid}` not found."}

    _clear_proposal(pid)
    try:
        sys.path.insert(0, SCRIPTS_DIR)
        import narrative_memory as _nm
        _nm.store_episode({"type": "action", "content": f"Proposal {pid} skipped by user", "metadata": {"proposal_id": pid, "action": proposal.get("action","?"), "outcome": "skipped"}})
        import feedback_loop
        feedback_loop.record_action("proposal_skipped", f"{pid}:{proposal.get('action','?')}")
    except Exception:
        pass

    return {"text": f"✅ Proposal `{pid}` skipped. It won't be retried."}


@handler("/proposals")
def handle_proposals(data):
    """List all pending proposals (for /list or admin check)."""
    proposals = []
    for f in PROPOSAL_DIR.glob("*.json"):
        try:
            proposals.append(json.loads(f.read_text()))
        except Exception:
            pass
    if not proposals:
        return {"text": "📭 No pending proposals."}
    lines = ["📋 **Pending proposals:**", ""]
    for p in proposals:
        age_min = (datetime.now() - datetime.fromisoformat(p["created"])).total_seconds() / 60
        lines.append(f"• `{p['id']}` [{p['action']}] ({int(age_min)}min ago)")
    return {"text": "\n".join(lines[:15])}
def handle_prometheus_query(data):
    query = data.get("query", "")
    if not query:
        return {"status": "error", "message": "query required"}
    try:
        import urllib.request
        url = f"http://127.0.0.1:9090/api/v1/query?query={urllib.parse.quote(query)}"
        resp = urllib.request.urlopen(url, timeout=10)
        return {"status": "ok", "data": json.loads(resp.read())}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@handler("/cert-check")
def handle_cert_check(data):
    import ssl
    import socket
    host = data.get("host", "")
    port = int(data.get("port", 443))
    if not host:
        return {"status": "error", "message": "host required"}
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=host) as s:
            s.settimeout(10)
            s.connect((host, port))
            cert = s.getpeercert()
            from datetime import datetime
            expires = datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
            days_left = (expires - datetime.utcnow()).days
            return {"status": "ok", "host": host, "expires": cert['notAfter'], "days_left": days_left, "subject": dict(x[0] for x in cert.get('subject', [])), "issuer": dict(x[0] for x in cert.get('issuer', []))}
    except Exception as e:
        return {"status": "error", "host": host, "message": str(e)}

@handler("/voice-transcribe")
def handle_voice_transcribe(data):
    """Transcribe a voice message file to text."""
    text = (data.get("args") or "").strip()
    if not text:
        return {"text": "Usage: /voice-transcribe <file_path> [--backend google-free]"}

    parts = text.split()
    file_path = parts[0]
    backend = None
    if "--backend" in parts:
        idx = parts.index("--backend")
        if idx + 1 < len(parts):
            backend = parts[idx + 1]

    script = f"{HERMES_HOME}/skills/voice-transcription/scripts/voice_transcribe.py"
    cmd = [sys.executable, script, "pipeline", file_path]
    if backend:
        cmd += ["--backend", backend]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if r.returncode == 0:
            import json as _json
            try:
                result = _json.loads(r.stdout.strip())
                if result.get("success"):
                    text_out = result.get("text", "")
                    backend_name = result.get("backend", "unknown")
                    note = result.get("note", "")
                    out = f"🎤 Transcribed ({backend_name}):\n{text_out[:500]}"
                    if note:
                        out += f"\n_{note}_"
                    # Relay transcription to Telegram
                    _call("/telegram-send", text=out, category="infra")
                    return {"text": out}
                return {"text": f"❌ Transcription failed: {result.get('error', 'unknown')}"}
            except _json.JSONDecodeError:
                return {"text": r.stdout.strip()[:500]}
        try:
            result = json.loads(r.stdout.strip() or r.stderr.strip())
            if result.get("error") or result.get("success") == False:
                return {"text": f"❌ voice-transcribe: {result.get('error', result.get('text','unknown'))}"}
        except (json.JSONDecodeError, TypeError):
            pass
        return {"text": f"❌ voice-transcribe: {r.stderr.strip()[:300] or r.stdout.strip()[:300]}"}
    except subprocess.TimeoutExpired:
        return {"text": "⏳ voice-transcribe: timed out"}
    except Exception as e:
        return {"text": f"❌ voice-transcribe: {str(e)}"}

@handler("/claude-save-session")
def handle_save_session(data):
    """Save current conversation context for later resumption."""
    topic = (data.get("args") or "").strip()
    if not topic:
        return {"text": "Usage: /claude-save-session <topic>"}

    context = data.get("context", "")
    if not context:
        # Build context from memory
        context = f"## Saved context for: {topic}\n## Timestamp: {datetime.utcnow().isoformat()}\n"

    script = f"{HERMES_HOME}/skills/session-handoff/scripts/session_handoff.py"
    try:
        r = subprocess.run([sys.executable, script, "save", topic, "--context", context],
                          capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            result = json.loads(r.stdout.strip())
            if result.get("success"):
                # Notify user
                sid = result.get("session_id", "?")
                return {"text": f"💾 Session saved: `{topic}` (id: {sid}) — use `/claude-resume-session {topic}` on your laptop"}
        return {"text": f"❌ save-session: {r.stderr.strip()[:200]}"}
    except Exception as e:
        return {"text": f"❌ save-session: {str(e)}"}

@handler("/claude-load-session")
def handle_load_session(data):
    """Load saved session context."""
    topic = (data.get("args") or "").strip()
    if not topic:
        return {"text": "Usage: /claude-load-session <topic>"}

    script = f"{HERMES_HOME}/skills/session-handoff/scripts/session_handoff.py"
    try:
        r = subprocess.run([sys.executable, script, "load", topic],
                          capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            try:
                result = json.loads(r.stdout.strip())
                if result.get("success"):
                    context = result.get("context", "")
                    return {"text": f"📥 Context loaded for `{topic}`:\n```\n{context[:400]}...\n```"}
                return {"text": f"❌ {result.get('error', 'unknown')}"}
            except json.JSONDecodeError:
                return {"text": r.stdout.strip()[:500]}
        return {"text": f"❌ load-session: {r.stderr.strip()[:200]}"}
    except Exception as e:
        return {"text": f"❌ load-session: {str(e)}"}

@handler("/claude-resume-session")
def handle_resume_session(data):
    """Resume a saved session on your laptop."""
    topic = (data.get("args") or "").strip()
    if not topic:
        return {"text": "Usage: /claude-resume-session <topic>"}

    script = f"{HERMES_HOME}/skills/session-handoff/scripts/session_handoff.py"
    try:
        r = subprocess.run([sys.executable, script, "resume", topic, "--task", f"Continue working on: {topic}"],
                          capture_output=True, text=True, timeout=360)
        if r.returncode == 0:
            try:
                result = json.loads(r.stdout.strip())
                if result.get("success"):
                    return {"text": result.get("text", f"✅ Resumed session for `{topic}`")[:500]}
                return {"text": f"❌ {result.get('error', 'unknown')}"}
            except json.JSONDecodeError:
                return {"text": r.stdout.strip()[:500]}
        return {"text": f"❌ resume-session: {r.stderr.strip()[:200]}"}
    except subprocess.TimeoutExpired:
        return {"text": "⏳ resume-session: timed out"}
    except Exception as e:
        return {"text": f"❌ resume-session: {str(e)}"}

@handler("/habit")
def handle_habit(data):
    """Telegram-facing habit tracker endpoint.
    /habit checkoff <id> yes|30m
    /habit prompts
    /habit streaks
    /habit goals
    """
    args_str = (data.get("args") or "").strip()
    if not args_str:
        return {"text": "Usage: /habit checkoff <id> <value> | /habit prompts | /habit streaks | /habit goals"}

    if args_str in ("prompts", "prompt", "daily", "today", "checklist"):
        cmd_args = ["daily-prompt"]
    elif args_str in ("summaries", "summary"):
        cmd_args = ["summary", "--format", "brief"]
    elif args_str in ("streaks", "streak"):
        cmd_args = ["streaks"]
    elif args_str in ("goals", "goal"):
        cmd_args = ["goals"]
    elif args_str.startswith("checkoff "):
        parts = args_str.split(maxsplit=2)
        cmd_args = ["checkoff", parts[1]]
        if len(parts) > 2:
            val = parts[2]
            if val.lower() in ("yes", "done", "y", "no", "skip"):
                cmd_args.append("--yes-no")
            else:
                cmd_args += ["--value", val]
    else:
        return {"text": f"Unknown habit subcommand. Try: checkoff, prompts, streaks, goals"}

    script = f"{HERMES_HOME}/skills/habit-tracker/scripts/habit_tracker.py"
    try:
        r = subprocess.run([sys.executable, script, *cmd_args],
                          capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return {"text": r.stdout.strip()[:2000]}
        return {"text": f"❌ habit: {r.stderr.strip()[:300]}"}
    except subprocess.TimeoutExpired:
        return {"text": "⏳ habit: timed out"}
    except Exception as e:
        return {"text": f"❌ habit: {str(e)}"}

@handler("/compose")
def handle_compose(data):
    """Multi-step plan decomposition + dispatch.
    /compose <goal>             # Decompose + dispatch
    /compose-dry <goal>         # Show plan without executing
    """
    text = (data.get("args") or "").strip()
    if not text:
        return {"text": "Usage: /compose <goal> | /compose-dry <goal>"}

    script = f"{HERMES_HOME}/skills/compose-planning/scripts/compose.py"
    dry = data.get("dry_run", False) or "dry" in data.get("command", "").lower()

    try:
        cmd = [sys.executable, script, "plan", text]
        if dry:
            cmd.append("--dry-run")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if r.returncode == 0:
            try:
                result = json.loads(r.stdout.strip())
                if result.get("text"):
                    # Send to Telegram
                    _call("/telegram-send", text=result["text"][:1500], category="infra")
                    return {"text": result["text"][:800]}
            except json.JSONDecodeError:
                return {"text": r.stdout.strip()[:500]}
        return {"text": f"❌ compose: {r.stderr.strip()[:300]}"}
    except subprocess.TimeoutExpired:
        return {"text": "⏳ compose: timed out (task too complex)"}
    except Exception as e:
        return {"text": f"❌ compose: {str(e)}"}

@handler("/memory")
def handle_memory(data):
    """Telegram-facing memory scanner endpoint.
    /memory scan — scan all categories
    /memory scan --categories stuck,todo
    /memory notify — scan + send report to Telegram
    /memory <query> — search episodic memory (fallback to unified_memory search)
    """
    args_str = (data.get("args") or "").strip()
    if not args_str:
        return {"text": "📣 Usage: /memory scan | /memory notify | /memory <query>"}

    scanner = f"{HERMES_HOME}/skills/memory-scanner/scripts/memory_scanner.py"

    if "notify" in args_str:
        try:
            r = subprocess.run([sys.executable, scanner, "notify"],
                              capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return {"text": r.stdout.strip()[:2000]}
            return {"text": f"❌ memory: {r.stderr.strip()[:300]}"}
        except subprocess.TimeoutExpired:
            return {"text": "⏳ memory: timed out"}
        except Exception as e:
            return {"text": f"❌ memory: {str(e)}"}
    elif args_str.startswith("scan"):
        cmd_args = ["scan"]
        if "--categories" in args_str:
            parts = args_str.split("--categories", 1)
            cmd_args.extend(["--categories", parts[1].strip()])
        elif args_str != "scan":
            cmd_args.extend(args_str.split())
        try:
            r = subprocess.run([sys.executable, scanner, *cmd_args],
                              capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return {"text": r.stdout.strip()[:2000]}
            return {"text": f"❌ memory: {r.stderr.strip()[:300]}"}
        except subprocess.TimeoutExpired:
            return {"text": "⏳ memory: timed out"}
        except Exception as e:
            return {"text": f"❌ memory: {str(e)}"}
    else:
        # Fallback: treat as query → search episodic memory
        r = _run_script("unified_memory.py", "search", args_str, "--top-k", "8", timeout=60)
        if r["success"]:
            return {"text": r["output"]}
        return {"text": f"❌ memory: {r.get('error','unknown')}"}

@handler("/all-services-status")
def handle_all_services_status(data):
    try:
        r = subprocess.run(
            ["sudo", "-u", "rohit", "env", "XDG_RUNTIME_DIR=/run/user/1000", "systemctl", "--user", "list-units", "--type=service", "--no-pager", "--plain", "--no-legend"],
            capture_output=True, text=True, timeout=10
        )
        heal = _heal_load_state()
        now = time.time()
        services = []
        for line in r.stdout.strip().split('\n'):
            parts = line.split(None, 4)
            if len(parts) >= 4:
                name = parts[0]
                st = heal.get(name, {})
                services.append({
                    "name": name, "load": parts[1], "active": parts[2], "sub": parts[3],
                    "description": parts[4] if len(parts) > 4 else "",
                    "heal_paused": st.get("paused_until", 0) > now,
                    "heal_failures": st.get("failures", 0),
                })
        return {"status": "ok", "services": services}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@handler("/docker-unhealthy")
def handle_docker_unhealthy(data):
    try:
        r = subprocess.run(
            ["docker", "ps", "--filter", "health=unhealthy", "--filter", "status=exited", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"],
            capture_output=True, text=True, timeout=10
        )
        containers = []
        for line in r.stdout.strip().split('\n'):
            if line:
                parts = line.split('\t', 2)
                containers.append({"name": parts[0], "status": parts[1] if len(parts)>1 else "", "image": parts[2] if len(parts)>2 else ""})
        return {"status": "ok", "count": len(containers), "containers": containers}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@handler("/docker-images")
def handle_docker_images(data):
    try:
        r = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"],
            capture_output=True, text=True, timeout=10
        )
        images = []
        for line in r.stdout.strip().split('\n'):
            if line:
                parts = line.split('\t', 2)
                images.append({"image": parts[0], "size": parts[1] if len(parts)>1 else "", "created": parts[2] if len(parts)>2 else ""})
        return {"status": "ok", "count": len(images), "images": images}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@handler("/run-cron")
def handle_run_cron(data):
    cmd = data.get("cmd", "")
    if not cmd:
        return {"status": "error", "message": "cmd required"}
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=data.get("timeout", 30))
        return ok_result(output=r.stdout[-5000:], stderr=r.stderr[-500:], returncode=r.returncode) if r.returncode == 0 else err_result(r.stderr[-500:])
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "timeout"}
    except Exception as e:
        return {"status": "error", "message": str(e)}



def handle_morning_briefing(data):
    """Aggregate all morning briefing data into one response."""
    from datetime import datetime
    HERMES = Path.home() / ".hermes"
    sections = []

    # Journal
    journal_dir = HERMES / "collaborator-memory" / "journal"
    if journal_dir.exists():
        journals = sorted(journal_dir.glob("*.md"))
        if journals:
            content = journals[-1].read_text()
            first_line = [l for l in content.split("\n") if l.strip() and not l.startswith("#") and not l.startswith("**")]
            if first_line:
                sections.append({"header": "Journal", "body": first_line[0][:80]})

    # Scheduler state
    state_file = HERMES / "data" / "scheduler_state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            results = {k: v for k, v in state.items() if isinstance(v, dict) and "last_status" in v}
            failures = sum(1 for v in results.values() if v.get("last_status") != "success")
            sections.append({"header": "Scheduler", "body": f"{state.get('jobs_run_count', 0)} runs, {failures} failures"})
        except: pass

    # Task queue
    queue_file = HERMES / "state" / "task_queue.json"
    if queue_file.exists():
        try:
            queue = json.loads(queue_file.read_text())
            tasks = queue.get("tasks", [])
            pending = len([t for t in tasks if t.get("status") == "pending"])
            escalated = len([t for t in tasks if t.get("status") == "escalated"])
            if pending or escalated:
                sections.append({"header": "Tasks", "body": f"{pending} pending, {escalated} escalated"})
        except: pass

    # Career
    career_file = HERMES / "data" / "career_briefing.json"
    if career_file.exists():
        try:
            career = json.loads(career_file.read_text())
            stats = career.get("stats", {})
            if stats:
                lines = []
                if stats.get("total_applications"): lines.append(f"Applied: {stats['total_applications']}")
                if stats.get("interviewing"): lines.append(f"Interviewing: {stats['interviewing']}")
                if stats.get("recent_jobs_24h"): lines.append(f"New (24h): {stats['recent_jobs_24h']}")
                if lines:
                    sections.append({"header": "Career", "body": " | ".join(lines)})
            recent = career.get("recent_matches", [])
            if recent:
                top = recent[0]
                sections.append({"header": "Top Match", "body": f"{top.get('score','?')} - {top.get('title','?')} @ {top.get('company','?')}"})
        except: pass

    # LLM costs
    cost_file = HERMES / "cost_logs" / "index.json"
    if cost_file.exists():
        try:
            cost = json.loads(cost_file.read_text())
            today = datetime.now().strftime("%Y-%m-%d")
            if today in cost.get("daily_costs", {}):
                today_cost = cost["daily_costs"][today]
                month_cost = sum(v for k, v in cost.get("daily_costs", {}).items() if k[:7] == today[:7])
                sections.append({"header": "LLM Costs", "body": f"Today: ${today_cost:.3f} | Month: ${month_cost:.3f}"})
        except: pass

    # Docker unhealthy
    try:
        r = subprocess.run(["docker", "ps", "--filter", "health=unhealthy", "--format", "{{.Names}}"],
                          capture_output=True, text=True, timeout=10)
        unhealthy = [n for n in r.stdout.strip().split("\n") if n.strip()]
        if unhealthy:
            sections.append({"header": "Unhealthy", "body": ", ".join(unhealthy)})
        else:
            sections.append({"header": "Containers", "body": "All healthy"})
    except: pass

    if not sections:
        sections.append({"header": "Status", "body": "No new signals yet."})

    return {"type": "morning_briefing", "date": datetime.now().strftime("%a %b %d"), "sections": sections}


def handle_evening_briefing(data):
    """Aggregate all evening briefing data into one response."""
    from datetime import datetime, timedelta
    HERMES = Path.home() / ".hermes"
    sections = []

    # Interest profile
    profile_file = HERMES / "data" / "interest_profile.json"
    if profile_file.exists():
        try:
            profile = json.loads(profile_file.read_text())
            if profile.get("dominant"):
                sections.append({"header": "Focus", "body": profile["dominant"]})
        except: pass

    # Proactive briefing
    brief_file = HERMES / "data" / "proactive_briefing.json"
    if brief_file.exists():
        try:
            brief = json.loads(brief_file.read_text())
            if brief.get("briefing", {}).get("pushed"):
                ts = brief.get("timestamp", "")
                if ts:
                    sections.append({"header": "Proactive", "body": f"Sent at {ts[11:16]} UTC"})
        except: pass

    # Activity summary
    for log_name, label in [("fix_log.jsonl", "Fixes"), ("deploy_log.jsonl", "Deploys"), ("discoveries.jsonl", "Discoveries")]:
        log_file = HERMES / "data" / log_name
        if log_file.exists():
            try:
                cutoff = datetime.now() - timedelta(hours=12)
                count = 0
                with open(log_file) as f:
                    for line in f:
                        try:
                            entry = json.loads(line.strip())
                            ts = entry.get("timestamp", "")
                            if ts and datetime.fromisoformat(ts) > cutoff:
                                count += 1
                        except: pass
                if count > 0:
                    sections.append({"header": label, "body": f"{count} in last 12h"})
            except: pass

    # Docker status
    try:
        r = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}|{{.State}}"],
                          capture_output=True, text=True, timeout=10)
        total = 0
        running = 0
        for line in r.stdout.strip().split("\n"):
            if not line.strip(): continue
            parts = line.split("|")
            total += 1
            if len(parts) > 1 and parts[1] == "running":
                running += 1
        sections.append({"header": "Containers", "body": f"{running}/{total} running"})
    except: pass

    if not sections:
        sections.append({"header": "Status", "body": "Quiet day."})

    return {"type": "evening_briefing", "date": datetime.now().strftime("%a %b %d"), "sections": sections}

class Handler(http.server.BaseHTTPRequestHandler):
    _NO_AUTH_GET = {
        "/ping", "/health-ping", "/system-health", "/docker-ps",
        "/disk-usage", "/metrics", "/all-services-status",
        "/docker-unhealthy", "/docker-images", "/code-graph/status",
        "/code-graph/repos",
    }
    _NO_AUTH_POST = {"/telegram-send"}

    def _from_trusted_source(self) -> bool:
        """Internal callers (loopback + docker/private subnets) are trusted.

        This bridge is private-LAN only (no external NAT for 9199). Workflows
        inside Docker reach the host via the docker0 gateway (172.x/16) and must
        be able to call operations such as `/service-restart` and `/run` without
        embedding an API token in workflow config.
        """
        import ipaddress
        try:
            ip = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return ip.is_loopback or ip.is_private or ip.is_link_local

    def check_auth(self, path=None):
        auth = self.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if path and path in SENSITIVE_PATHS:
            return bool(token) and token == AUTH_KEY
        if self._from_trusted_source():
            return True
        return bool(token) and token == AUTH_KEY

    def _auth_required(self, path, method):
        if method == "GET" and path in self._NO_AUTH_GET:
            return False
        if method == "POST" and path in self._NO_AUTH_POST:
            return False
        return True

    def _deny(self):
        body = json.dumps({"error": "unauthorized"}).encode()
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)
    
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if self._auth_required(parsed.path, "GET") and not self.check_auth(parsed.path):
            return self._deny()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        data = {k: v[0] if len(v) == 1 else v for k, v in params.items()}
        handler_fn = HANDLERS.get(path)
        if handler_fn:
            result = handler_fn(data)
            self.wfile.write(json.dumps(result).encode())
        else:
            self.wfile.write(json.dumps({"error": "not found", "paths": list(HANDLERS.keys())}).encode())

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if self._auth_required(parsed.path, "POST") and not self.check_auth(parsed.path):
            return self._deny()
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len else b"{}"
        data = json.loads(body) if body else {}
        parsed = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed.query)
        for k, v in query_params.items():
            if k not in data:
                data[k] = v[0] if len(v) == 1 else v
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        path = parsed.path
        handler_fn = HANDLERS.get(path)
        if handler_fn:
            result = handler_fn(data)
            self.wfile.write(json.dumps(result).encode())
        else:
            self.wfile.write(json.dumps({"error": "not found", "paths": list(HANDLERS.keys())}).encode())

    def log_message(self, format, *args):
        pass


def _telegram_get_updates(offset: int = 0) -> dict | None:
    """Long-poll Telegram getUpdates. Returns the API response or None on error."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"offset": offset + 1, "timeout": 25, "allowed_updates": ["message"]}
    try:
        parsed = urllib.parse.urlencode(params)
        req = urllib.request.Request(f"{url}?{parsed}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _telegram_send_text(chat_id: int, text: str, message_thread_id: int | None = None):
    """Send a text reply back to the Telegram chat."""
    payload = {"chat_id": str(chat_id), "text": text, "parse_mode": "Markdown"}
    if message_thread_id:
        payload["message_thread_id"] = str(message_thread_id)
    _send_telegram_api(chat_id, text, parse_mode="Markdown", message_thread_id=message_thread_id)


def _telegram_poller():
    """Background thread: polls Telegram for incoming commands and routes them."""
    import threading
    state_file = Path.home() / ".hermes" / "state" / "telegram_offset.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)

    def loop():
        offset = 0
        if state_file.exists():
            try:
                offset = json.loads(state_file.read_text()).get("offset", 0)
            except Exception:
                offset = 0

        while True:
            try:
                updates = _telegram_get_updates(offset)
                if updates and updates.get("ok"):
                    for update in updates.get("result", []):
                        offset = update["update_id"]
                        msg = update.get("message", {})
                        if not msg or not msg.get("text"):
                            continue
                        text = msg["text"].strip()
                        chat = msg.get("chat", {})
                        chat_id = chat.get("id")
                        thread_id = msg.get("message_thread_id") or chat.get("message_thread_id") or None

                        # Record active chat/thread so queued host applies reply to this topic.
                        global _tg_chat_ctx
                        _tg_chat_ctx = {"chat_id": chat_id, "thread_id": thread_id}

                        # Route command through existing router
                        result = _route_telegram_command(text)

                        # Send the response back to Telegram
                        if result and "text" in result:
                            _telegram_send_text(chat_id, result["text"][:4096], message_thread_id=thread_id)


                        # Save offset
                        state_file.write_text(json.dumps({"offset": offset}))
                time.sleep(1)
            except Exception as e:
                print(f"[telegram-poller] error: {e}", file=sys.stderr)
                time.sleep(5)

    t = threading.Thread(target=loop, daemon=True, name="telegram-poller")
    t.start()
    print("Telegram long-polling receiver started", flush=True)


def main():
    HOST = os.environ.get("N8N_BRIDGE_HOST", "0.0.0.0")
    server = http.server.HTTPServer((HOST, PORT), Handler)
    print(f"n8n bridge on {HOST}:{PORT}", flush=True)
    print(f"Endpoints: {list(HANDLERS.keys())}", flush=True)

    # Telegram long-polling receiver (optional). DISABLED by default: the
    # hermes-gateway already polls getUpdates for this bot, and two concurrent
    # getUpdates sessions on the same token cause a permanent 409 polling
    # conflict. Only enable if the gateway's Telegram platform is turned off.
    if os.environ.get("BRIDGE_TELEGRAM_POLLER", "0") == "1":
        _telegram_poller()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()

# ── Code Review Graph endpoints ──────────────────────────────────────────
import subprocess, json as _json
from pathlib import Path as _Path
_CRG = "/home/rohit/.local/bin/code-review-graph"
_CRG_DEFAULT_REPO = "/home/rohit/.hermes"
_CRG_REGISTRY = _Path.home() / ".code-review-graph" / "registry.json"

def _crg_repo_path(repo: str) -> str:
    """Resolve a repo alias or path to a CRG-registered repository root.

    Accepts:
      - an alias registered in registry.json (hermes-agent,
        hermes-scripts, career-ops, collaborator-memory, home)
      - an absolute path to any registered repo
    Falls back to the default repo when nothing matches.
    """
    if not repo:
        return _CRG_DEFAULT_REPO
    try:
        reg = _json.loads(_CRG_REGISTRY.read_text())
        entries = reg.get("repos", [])
    except Exception:
        entries = []
    for entry in entries:
        if repo in (entry.get("alias"), entry.get("path")):
            return entry["path"]
    return repo if str(repo).startswith("/") else _CRG_DEFAULT_REPO

def _crg(*args, repo: str = ""):
    resolved = _crg_repo_path(repo)
    try:
        r = subprocess.run(
            [_CRG] + list(args) + ["--repo", resolved],
            capture_output=True, text=True, timeout=45,
        )
        return {"success": r.returncode == 0, "output": r.stdout, "error": r.stderr}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "timed out"}

def _clean_lines(out: str) -> str:
    return "\n".join(
        l for l in out.split("\n") if not l.startswith("INFO:") and l.strip()
    )

@handler("/code-graph/status")
def _cg_status(data):
    r = _crg("status", repo=data.get("repo", ""))
    if r["success"]:
        return {"text": r["output"]}
    return {"error": r["error"]}

@handler("/code-graph/dead-code")
def _cg_dead(data):
    r = _crg("dead-code", repo=data.get("repo", ""))
    if r["success"]:
        return {"text": _clean_lines(r["output"])}
    return {"error": r["error"]}

@handler("/code-graph/query")
def _cg_query(data):
    qtype = data.get("type", "callers_of")
    target = data.get("target", "")
    if not target:
        return {"error": "target required"}
    r = _crg("query", qtype, target, repo=data.get("repo", ""))
    if r["success"]:
        return {"text": _clean_lines(r["output"])}
    return {"error": r["error"]}

@handler("/code-graph/search")
def _cg_search(data):
    q = data.get("q", "")
    if not q:
        return {"error": "q required"}
    r = _crg("search", q, repo=data.get("repo", ""))
    if r["success"]:
        return {"text": _clean_lines(r["output"])}
    return {"error": r["error"]}

@handler("/code-graph/impact")
def _cg_impact(data):
    files = data.get("files", "")
    if not files:
        return {"error": "files required (comma-separated)"}
    r = _crg("detect-changes", "--files", files, repo=data.get("repo", ""))
    if r["success"]:
        return {"text": _clean_lines(r["output"])}
    return {"error": r["error"]}

@handler("/code-graph/architecture")
def _cg_arch(data):
    r = _crg("architecture", repo=data.get("repo", ""))
    if r["success"]:
        return {"text": _clean_lines(r["output"])}
    return {"error": r["error"]}

@handler("/code-graph/flows")
def _cg_flows(data):
    r = _crg("flows", repo=data.get("repo", ""))
    if r["success"]:
        return {"text": _clean_lines(r["output"])}
    return {"error": r["error"]}

@handler("/code-graph/repos")
def _cg_repos(data):
    try:
        reg = _json.loads(_CRG_REGISTRY.read_text())
        rows = [
            f"- `{e.get('alias')}` -> {e.get('path')}"
            for e in reg.get("repos", [])
        ]
        return {"text": "Registered repos:\n" + "\n".join(rows)}
    except Exception as e:
        return {"error": f"could not read registry: {e}"}


_GRAPHIFY = "/home/rohit/.local/bin/graphify"

@handler("/graphify")
def _gf(data):
    cmd = (data.get("cmd") or "").strip()
    if not cmd:
        return {"text": "Usage: /graphify <command> [args]\nCommands: path, explain, diagnose"}
    try:
        r = subprocess.run([_GRAPHIFY] + cmd.split(), capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return {"text": r.stdout[:3000]}
        return {"text": "\u274c " + r.stderr[:500]}
    except subprocess.TimeoutExpired:
        return {"text": "\u23f3 graphify timed out"}
    except Exception as e:
        return {"text": "\u26a0 graphify error: " + str(e)}

@handler("/graphify-path")
def _gf_path(data):
    a = (data.get("args") or "").strip()
    if not a:
        return {"text": "Usage: /graphify-path <node-a> <node-b>"}
    parts = a.split()
    if len(parts) < 2:
        return {"text": "Need two node names: /graphify-path <node-a> <node-b>"}
    try:
        r = subprocess.run([_GRAPHIFY, "path", parts[0], parts[1]], capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return {"text": r.stdout[:3000]}
        return {"text": "\u274c " + r.stderr[:500]}
    except subprocess.TimeoutExpired:
        return {"text": "\u23f3 timed out"}
    except Exception as e:
        return {"text": "\u26a0 error: " + str(e)}

@handler("/graphify-explain")
def _gf_explain(data):
    target = (data.get("target") or data.get("args", "").strip()).strip()
    if not target:
        return {"text": "Usage: /graphify-explain <node-name>"}
    try:
        r = subprocess.run([_GRAPHIFY, "explain", target], capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return {"text": r.stdout[:3000]}
        return {"text": "\u274c " + r.stderr[:500]}
    except subprocess.TimeoutExpired:
        return {"text": "\u23f3 timed out"}
    except Exception as e:
        return {"text": "\u26a0 error: " + str(e)}
# ── Subsystem handlers: ledger, commitments, queue, digest, doctor, ─────────
# ── memory, proactive, cap, cost, routing ──────────────────────────────────
import os
import sys
import json
import subprocess
from pathlib import Path

_HH = Path.home() / ".hermes"


def _run_script(name, *args, timeout=60, cwd=None):
    try:
        r = subprocess.run(
            [sys.executable, str(_HH / "scripts" / name), *args],
            capture_output=True, text=True, timeout=timeout, cwd=cwd or str(_HH),
        )
        return {"success": r.returncode == 0, "output": r.stdout[-3000:], "error": r.stderr[-500:], "code": r.returncode}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "timed out", "code": -1}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e), "code": -1}


def _load_json(relpath, default=None):
    p = _HH / relpath
    try:
        if not p.exists():
            return default
        return json.loads(p.read_text())
    except OSError:
        return default
    except Exception:
        return default


@handler("/ledger")
def _sys_ledger(data):
    args = (data.get("args") or "recent").split()
    sub = args[0] if args else "recent"
    if sub == "stats":
        r = _run_script("decision_ledger.py", "stats")
    else:
        limit = args[1] if len(args) > 1 and args[1].isdigit() else "10"
        r = _run_script("decision_ledger.py", "recent", "--limit", limit)
    if not r["success"]:
        return {"text": "❌ ledger: " + (r["error"] or r["output"])}
    lines = [l for l in r["output"].split("\n") if l.strip() and not l.startswith("INFO:")]
    return {"text": "📒 Decision Ledger\n" + "\n".join(lines)}


@handler("/commitments")
def _sys_commitments(data):
    args = (data.get("args") or "status").split()
    sub = args[0] if args else "status"
    if sub == "overdue":
        r = _run_script("commitment_tracker.py", "--overdue")
    else:
        r = _run_script("commitment_tracker.py", "--status")
    if not r["success"]:
        return {"text": "❌ commitments: " + (r["error"] or r["output"])}
    try:
        obj = json.loads(r["output"])
        active = obj.get("active", obj.get("active_count", []))
        if isinstance(active, int):
            text = f"📌 Commitments\nActive: {active} | History: {obj.get('history_count', '?')}"
            stats = obj.get("stats", {})
            if stats:
                text += f"\nMade: {stats.get('total_made', 0)} | Fulfilled: {stats.get('total_fulfilled', 0)} | On-time: {stats.get('on_time_rate', 0)}%"
            upcoming = obj.get("upcoming", [])
            if upcoming:
                text += "\n\n⏰ Due soon:"
                for c in upcoming[:5]:
                    text += f"\n  • {c.get('id', '?')[:8]}: {c.get('text', '')[:80]}"
            return {"text": text}
        text = f"📌 Commitments ({obj.get('active_count', 0)} active)"
        for c in obj.get("active", [])[:10]:
            dl = c.get("deadline") or "no deadline"
            text += f"\n  • `{c['id']}` {c.get('text', '')[:90]} (due {dl[:16]})"
        return {"text": text}
    except Exception:
        return {"text": "📌 Commitments\n" + r["output"][:1500]}


@handler("/queue")
def _sys_queue(data):
    q = _load_json("state/task_queue.json")
    if not q:
        return {"text": "🗂 Task queue: no data"}
    tasks = q.get("tasks", [])
    text = f"🗂 Task Queue ({len(tasks)} queued)"
    for t in tasks[:10]:
        status = t.get("status", "?")
        icon = "✅" if status == "completed" else ("⏳" if status == "pending" else "❌")
        text += f"\n  {icon} [{t.get('priority', '?')}] {t.get('title', '')[:90]}"
    if q.get("cleared"):
        text += f"\n\n🧹 {len(q['cleared'])} cleared items"
    return {"text": text}


@handler("/digest")
def _sys_digest(data):
    r = _run_script("hermes_digest.py")
    if not r["success"]:
        return {"text": "❌ digest: " + (r["error"] or r["output"])}
    try:
        o = json.loads(r["output"])
        text = f"📊 Daily Digest ({o.get('date', '')[:10]})\n"
        text += f"Actions taken: {o.get('actions_taken', 0)}\n"
        mem = o.get("memory", {})
        text += f"Memory: {mem.get('total_actions', 0)} actions, {mem.get('in_cooldown', 0)} in cooldown\n"
        con = o.get("containers", {})
        text += f"Containers: {con.get('total', 0)} total, {con.get('unhealthy', 0)} unhealthy"
        recent = o.get("recent_decisions", [])
        if recent:
            text += "\n\nRecent:"
            for d in recent[-5:]:
                text += f"\n  • {d}"
        return {"text": text}
    except Exception:
        return {"text": "📊 Daily Digest\n" + r["output"][:1500]}


@handler("/doctor")
def _sys_doctor(data):
    r = _run_script("system_doctor.py", timeout=120)
    lines = [l for l in r["output"].split("\n") if l.strip()]
    action_lines = [l for l in lines if "  - " in l]
    if not action_lines:
        return {"text": "🩺 System Doctor: all clear — no issues found"}
    text = "🩺 System Doctor run:\n" + "\n".join(action_lines[:15])
    return {"text": text}


def _sys_memory_old(data):
    """Deprecated: use /memory scan or /memory notify instead."""
    q = (data.get("args") or "").strip()
    if not q:
        return {"text": "🔎 Usage: /memory <query> | /memory scan | /memory notify"}
    r = _run_script("unified_memory.py", "search", q, "--top-k", "8", timeout=90)
    if not r["success"]:
        return {"text": "❌ memory: " + (r["error"] or r["output"])}
    lines = [l for l in r["output"].split("\n") if l.strip() and not l.startswith("INFO:")]
    if not lines:
        return {"text": f"🔎 No memory matches for: {q}"}
    text = f"🔎 Memory search: {q}\n" + "\n".join(lines[:12])
    return {"text": text}


@handler("/predict")
def _sys_predict(data):
    """Show proactive predictions from trend analysis."""
    r = _run_script("predictive_signals.py", "--show", timeout=60)
    if not r["success"]:
        return {"text": "❌ predict: " + (r["error"] or r["output"][:200])}
    lines = [l for l in r["output"].split("\n") if l.strip() and not l.startswith("INFO:")]
    if not lines:
        return {"text": "📊 Predictive analysis: no predictions yet (insufficient data). Run for 24h+ to build trends."}
    text = "🔮 Proactive Predictions\n" + "\n".join(lines[:15])
    return {"text": text}


@handler("/kg")
def _sys_kg(data):
    """Query the Semantic Knowledge Graph."""
    import sys as _sys
    _sys.path.insert(0, str(_HH / "knowledge_graph"))
    from kg_engine import natural_query, search_nodes, get_all_types

    q = (data.get("args") or "").strip()
    if not q:
        stats = get_all_types()
        text = "🧠 Knowledge Graph — Overview"
        text += f"\n📊 Nodes: {stats['total_nodes']} | Edges: {stats['total_edges']}"
        for t, c in sorted(stats["node_types"].items(), key=lambda x: -x[1]):
            text += f"\n  {t}: {c}"
        text += "\n\n🔍 Try: /kg people at Microsoft | /kg topics related to Career | /kg Session: 20260601"
        return {"text": text}

    try:
        result = natural_query(q)
    except Exception as e:
        return {"text": f"❌ kg query error: {e}"}

    if result.get("type") == "people_at_company":
        company = result.get("company", "?")
        people = result.get("people", [])
        if people:
            text = f"👥 People connected to {company}:"
            for p in people:
                props = json.loads(p.get("properties") or "{}")
                text += f"\n  • {p['label']}"
                if props.get("role"):
                    text += f" — {props['role']}"
                if props.get("relationship"):
                    text += f" ({props['relationship']})"
        else:
            text = f"👥 No people found connected to {company} in KG"
    elif result.get("type") == "related_topics":
        topics = result.get("result", [])
        if topics:
            text = "🔗 Related topics:"
            for t in topics:
                text += f"\n  • {t['label']} ({t['relation']}, conf={t.get('confidence',1):.2f})"
        else:
            text = "🔗 No related topics found"
    elif result.get("type") == "session_context":
        sc = result.get("result", {})
        if "error" in sc:
            text = f"🔍 {sc['error']}"
        else:
            s = sc.get("session", {})
            text = f"📋 Session: {s.get('label', '?')}"
            for topic in sc.get("topics", []):
                text += f"\n  📊 Topic: {topic}"
            for goal in sc.get("goals", []):
                text += f"\n  🎯 Goal: {goal}"
            for tool in sc.get("tools", []):
                text += f"\n  🔧 Tool: {tool}"
            for e in sc.get("entities", []):
                text += f"\n  👤 Entity: {e['label']} ({e['type']})"
    elif result.get("type") == "connections":
        r = result.get("result", {})
        paths = r.get("paths", [])
        people_at = r.get("people_at_company", [])
        text = f"🔗 Connections: {r.get('person', {}).get('label', '?')} ↔ {r.get('company', {}).get('label', '?')}"
        for p in paths:
            text += f"\n  Path ({p['type']}): " + " → ".join(
                f"{x.get('relation','')}" for x in p.get("edges", p if isinstance(p, list) else [])
            )
        if people_at:
            text += "\nPeople at company:"
            for p in people_at:
                text += f"\n  • {p.get('label')}"
    elif result.get("type") in ("people", "companies", "topics"):
        items = result.get(result["type"], [])
        if items:
            label = {"people": "👤", "companies": "🏢", "topics": "📊"}[result["type"]]
            text = f"{label} {result['type'].capitalize()}:"
            for n in items[:15]:
                text += f"\n  • {n.get('label', '?')} (x{n.get('mention_count',1)})"
        else:
            text = f"No {result['type']} found"
    elif result.get("type") == "search":
        results = result.get("results", [])
        if results:
            text = f"🔍 Search: '{result.get('query','')}'"
            for n in results[:10]:
                props = {}
                if n.get("properties"):
                    try:
                        props = json.loads(n["properties"])
                    except:
                        pass
                text += f"\n  • [{n.get('type','?')}] {n.get('label','?')} (x{n.get('mention_count',1)})"
                if props.get("role") or props.get("relationship"):
                    text += f" — {props.get('role','')} {props.get('relationship','')}".strip()
        else:
            text = f"🔍 No results for '{result.get('query','')}'"
    elif result.get("type") == "recent_sessions":
        sessions = result.get("sessions", [])
        if sessions:
            text = "📅 Recent Sessions:"
            for s in sessions[:10]:
                text += f"\n  • {s.get('label','?')}"
        else:
            text = "📅 No recent sessions found"
    else:
        text = json.dumps(result, indent=2, default=str)[:500]

    return {"text": text, "category": "briefing", "priority": "normal"}


@handler("/proactive")
def _sys_proactive(data):
    """Show proactive engine snapshot, KG-enhanced."""
    snap = _load_json("state/proactive_engine_snapshot.json")
    brief = _load_json("data/proactive_briefing.json")
    text = "🧠 Proactive Engine"

    # KG-enhanced context: what was recently discussed?
    import sys as _sys
    _sys.path.insert(0, str(_HH / "knowledge_graph"))
    from kg_engine import recent_sessions, get_all_types

    try:
        recent = recent_sessions(limit=3, since_hours=24)
        if recent:
            text += "\n\n🔗 KG — Recent activity (24h):"
            for s in recent:
                label = s.get("label", "?")
                # Truncate long session labels
                if len(label) > 60:
                    label = label[:60] + "…"
                text += f"\n  • {label}"
    except Exception:
        pass

    try:
        stats = get_all_types()
        text += f"\n📊 KG: {stats['total_nodes']} nodes, {stats['total_edges']} edges"
    except Exception:
        pass

    if snap:
        keys = ["last_cycle", "items_pushed", "paused", "enabled", "state"]
        for k in keys:
            if k in snap:
                v = snap[k]
                text += f"\n{k}: {json.dumps(v)[:120] if isinstance(v, (dict, list)) else v}"
    elif brief:
        text += "\n(last briefing " + str(brief.get("timestamp", "?")) + ")"
    else:
        text += "\nNo snapshot data found"
    return {"text": text, "category": "briefing", "priority": "normal"}


@handler("/graph")
def _sys_graph(data):
    """Expose graphify+CRG graph capabilities: find entities, trace edges."""
    args = (data.get("args") or "").split()
    if not args:
        text = "🕸 Usage: /graph <symbol|entity> [mode: callers|callees|deps|kg]"
        return {"text": text, "category": "briefing", "priority": "normal"}

    target = args[0]
    mode = args[1] if len(args) > 1 else "kg"

    if mode == "kg":
        # Semantic KG query via kg_engine
        _sys.path.insert(0, str(_HH / "knowledge_graph"))
        from kg_engine import natural_query
        try:
            result = natural_query(target)
            # Pretty-print the natural query result
            if result.get("type") == "search":
                results = result.get("results", [])
                if results:
                    text = f"🧠 KG search: {target}"
                    for n in results[:8]:
                        props = {}
                        if n.get("properties"):
                            try:
                                props = json.loads(n["properties"])
                            except:
                                pass
                        extra = ""
                        if props.get("role") or props.get("relationship"):
                            extra = f" — {props.get('role','')} {props.get('relationship','')}".strip()
                        text += f"\n  • [{n.get('type','?')}] {n.get('label','?')} (x{n.get('mention_count',1)}){extra}"
                else:
                    text = f"🔍 No KG results for: {target}"
            elif result.get("type") == "connections":
                r = result.get("result", {})
                paths = r.get("paths", [])
                people_at = r.get("people_at_company", [])
                text = f"🔗 {r.get('person', {}).get('label', '?')} ↔ {r.get('company', {}). get('label', '?')}"
                for p in paths:
                    text += f"\n  Path ({p.get('type','')}) — " + " -> ".join(
                        edge.get("relation", "→") for edge in p.get("edges", [])
                    )[:150]
                if people_at:
                    text += "\nPeople at company:"
                    for p in people_at[:8]:
                        text += f"\n  • {p.get('label')}"
            elif "edges" in result:
                edges = result["edges"]
                if edges:
                    text = f"🔗 {result.get('type','')}: {target}"
                    for e in edges[:10]:
                        text += f"\n  {e.get('src_label','')} --{e.get('relation','')}--> {e.get('tgt_label','')}"
                else:
                    text = f"No edges found for: {target}"
            else:
                text = f"🧠 KG: {json.dumps(result, indent=2, default=str)[:500]}"
        except Exception as e:
            text = f"❌ kg: {e}"
    else:
        # CRG graph query
        r = _run_script("crg_context.py", "--query", " ".join(args), timeout=60)
        if not r["success"]:
            return {"text": f"❌ graph: {r['error'] or r['output'][:200]}"}
        text = r["output"][:2000]

    return {"text": text, "category": "briefing", "priority": "normal"}


@handler("/search")
def _sys_search(data):
    """Search across Unified Memory, KG, and CRG."""
    q = (data.get("args") or "").strip()
    if not q:
        return {"text": "🔎 Usage: /search <query> — searches memory + knowledge graph"}

    import sys as _sys

    # 1. Unified memory search
    mem_results = []
    r = _run_script("unified_memory.py", "search", q, "--top-k", "5", timeout=90)
    if r["success"]:
        lines = [l for l in r["output"].split("\n") if l.strip() and not l.startswith("INFO:")]
        mem_results = lines[:10]

    # 2. KG search
    kg_results = []
    _sys.path.insert(0, str(_HH / "knowledge_graph"))
    try:
        from kg_engine import search_nodes
        nodes = search_nodes(q, limit=8)
        for n in nodes:
            kg_results.append(f"[{n.get('type','?')}] {n.get('label','?')} (x{n.get('mention_count',1)})")
    except Exception:
        pass

    # 3. CRG semantic search
    crg_results = []
    r2 = _run_script("crg_context.py", "--semantic", q, timeout=60)
    if r2["success"]:
        lines = [l for l in r2["output"].split("\n") if l.strip()]
        crg_results = lines[:5]

    text = f"🔎 Search results for: {q}"
    if mem_results:
        text += "\n\n💾 Memory:"
        for l in mem_results:
            text += f"\n  {l[:200]}"
    if kg_results:
        text += "\n\n🧠 Knowledge Graph:"
        for l in kg_results:
            text += f"\n  • {l[:200]}"
    if crg_results:
        text += "\n\n🆔 CRG Semantic:"
        for l in crg_results:
            text += f"\n  {l[:200]}"

    if not mem_results and not kg_results and not crg_results:
        text += "\n\nNo results found across memory, KG, or CRG."

    return {"text": text, "category": "briefing", "priority": "normal"}


@handler("/proactive")
def _sys_proactive(data):
    snap = _load_json("state/proactive_engine_snapshot.json")
    brief = _load_json("data/proactive_briefing.json")
    text = "🧠 Proactive Engine"

    # KG-enhanced context: what was recently discussed?
    import sys as _sys
    _sys.path.insert(0, str(_HH / "knowledge_graph"))
    from kg_engine import recent_sessions, get_all_types

    try:
        recent = recent_sessions(limit=3, since_hours=24)
        if recent:
            text += "\n\n🔗 KG — Recent activity (24h):"
            for s in recent:
                label = s.get("label", "?")
                if len(label) > 60:
                    label = label[:60] + "\u2026"
                text += f"\n  \u2022 {label}"
    except Exception:
        pass

    try:
        stats = get_all_types()
        text += f"\n\uDCEF KG: {stats['total_nodes']} nodes, {stats['total_edges']} edges"
    except Exception:
        pass

    if snap:
        keys = ["last_cycle", "items_pushed", "paused", "enabled", "state"]
        for k in keys:
            if k in snap:
                v = snap[k]
                text += f"\n{k}: {json.dumps(v)[:120] if isinstance(v, (dict, list)) else v}"
    elif brief:
        text += "\n(last briefing " + str(brief.get("timestamp", "?")) + ")"
    else:
        text += "\nNo snapshot data found"
    return {"text": text, "category": "briefing", "priority": "normal"}


@handler("/cap")
def _sys_cap(data):
    import yaml
    cfg_path = _HH / "config.yaml"
    try:
        cfg = yaml.safe_load(cfg_path.read_text())
    except Exception as e:
        return {"text": "❌ cap: cannot read config.yaml: " + str(e)}
    providers = (cfg.get("proxy", {}).get("providers", {}) or {})
    text = "💰 Provider caps"
    for name, p in providers.items():
        enabled = "✅" if p.get("enabled") else "⛔"
        text += f"\n  {enabled} {name}: ${p.get('daily_limit', 0)}/day — {p.get('model', '?')}"
    return {"text": text}


@handler("/cost")
def _sys_cost(data):
    r = _run_script("unified_cost_guard.py", "status", timeout=60)
    if not r["success"]:
        return {"text": "❌ cost: " + (r["error"] or r["output"])}
    lines = [l for l in r["output"].split("\n") if l.strip() and not l.startswith("INFO:")]
    return {"text": "💵 Cost Guard status\n" + "\n".join(lines[:20])}


@handler("/jobs-latest")
def _jobs_latest(data):
    """Latest job applications from the career-ops ledger (Hop)."""
    import sqlite3, pathlib, os
    db = pathlib.Path.home() / "projects" / "career-ops" / "data" / "applications.db"
    if not db.exists():
        return {"text": "\u26a0\ufe0f career-ops applications.db not present yet"}
    try:
        con = sqlite3.connect(f"file:{db}?immutable=1", uri=True, timeout=15)
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(
            "SELECT rowid, company, title, status, score, report_path, cover_letter_path, created_at, updated_at FROM applications ORDER BY rowid DESC LIMIT 4")]
        con.close()
    except Exception as e:
        return {"text": f"\u26a0\ufe0f latest jobs: {e}"}
    if not rows:
        return {"text": "\U0001f4ed No applications logged yet \u2014 first pipeline run seeds this."}
    out = ["\U0001f4cb **Latest applications**"]
    for r in rows:
        st = r.get("status") or "saved"
        line = f"\u2022 **{r['company']}** \u2014 {r['title']}\n    \u00b7 {st} \u00b7 score {r.get('score','-')} \u00b7 {str(r.get('updated_at') or r.get('created_at'))[:10]}"
        out.append(line)
        for tag, col in (("\U0001f4c4 report", "report_path"), ("\u2709\ufe0f cover", "cover_letter_path")):
            v = r.get(col)
            if v:
                out.append(f"    {tag}: `{os.path.basename(v)}`")
    out.append("")
    out.append("\U0001f5c2 Full set: `Job Hunt/September 2026/` on GDrive")
    return {"text": "\n".join(out)}


@handler("/providers-status")
def _providers_status(data):
    """Provider availability + cost ledger, one summary (Hop)."""
    import pathlib, json, subprocess, os
    home = pathlib.Path.home()
    lines = ["\U0001f5a5 **Providers status**", ""]

    # 1) In-use model + free provider list (real data, container paths)
    guard_dir = home / "shared" / "zero_cost_guard"
    cfg = {}
    try:
        cfg = json.loads((guard_dir / "config.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    sts = {}
    try:
        sts = json.loads((guard_dir / "state.json").read_text(encoding="utf-8"))
    except Exception:
        pass

    model = sts.get("current_model", "unknown")
    lines.append("\U0001f305 **In use**")
    lines.append(f"  `{model}`")
    lines.append("")

    free = cfg.get("free_models") or []
    if free:
        lines.append("\U0001f3c1 **Available free providers**")
        provs = []
        for m in free:
            prov = m.split("/")[0] if "/" in m else m
            provs.append(prov)
        # unique, show up to 12
        seen = []
        for pv in provs:
            if pv not in seen:
                seen.append(pv)
        lines.append("  " + ", ".join(f"\U0001f7e2 {pv}" for pv in seen[:12]))
        lines.append("")

    # 2) Billing/cost ledger — reuse the actual guard script output
    lines.append("\U0001f4b8 **Cost guard**")
    try:
        out = subprocess.run([sys.executable or "python3", str(guard_dir / "zero_cost_guard.py"), "status"],
                             capture_output=True, text=True, timeout=20).stdout
        # compact: keep the 3 relevant sections
        keep = []
        for sec in out.split("\n\n"):
            if sec.strip().startswith(("===","\u2501")) or "OpenRouter" in sec or "model" in sec[:40]:
                keep.append(sec.strip()[:400])
        if keep:
            lines.append("\n".join("  " + l for l in keep[0].splitlines()))
        else:
            lines.append("  (see /cost for full detail)")
    except Exception as e:
        lines.append(f"  (cost guard unavailable: {str(e)[:40]})")
    lines.append("")

    return {"text": "\n".join(lines)}

@handler("/routing")
def _sys_routing(data):
    import yaml
    args = (data.get("args") or "status").split()
    cfg_path = _HH / "config.yaml"
    try:
        cfg = yaml.safe_load(cfg_path.read_text())
        providers = cfg.get("proxy", {}).get("providers", {}) or {}
    except Exception as e:
        return {"text": "❌ routing: " + str(e)}
    action = args[0] if args else "status"
    if action == "status":
        text = "🛣 Routing providers"
        for name, p in providers.items():
            enabled = "✅" if p.get("enabled") else "⛔"
            text += f"\n  {enabled} {name} — {p.get('model', '?')}"
        return {"text": text}
    if action in ("enable", "disable"):
        target = args[1] if len(args) > 1 else ""
        if target not in providers:
            return {"text": f"❌ routing: unknown provider '{target}'"}
        providers[target]["enabled"] = (action == "enable")
        cfg["proxy"]["providers"] = providers
        cfg_path.write_text(yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False))
        return {"text": f"🛣 {action}d provider: {target}"}
    if action == "reset":
        for p in providers.values():
            p["enabled"] = True
        cfg["proxy"]["providers"] = providers
        cfg_path.write_text(yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False))
        return {"text": "🛣 reset: all providers enabled"}
    return {"text": "🛣 Usage: /routing [status|enable <name>|disable <name>|reset]"}


@handler("/ask")
def _sys_ask(data):
    """Push a notification to the Telegram channel.

    Supports category-aware routing via /ask --category <cat> <message>.
    Without a category, the message goes to the default channel (General).
    Categories route to forum topics: career→7338, homelab→7343, infra→7356.

    Also supports /ask --broadcast <message> to send to ALL topics.
    """
    args = (data.get("args") or "").strip()
    if not args:
        return {"text": "📣 Usage: /ask <message>\n📣 Or: /ask --category career|homelab|infra <message>\n📣 Or: /ask --broadcast <message>"}

    # Parse optional flags
    category = None
    broadcast = False
    category_map = {
        "career": "career",
        "career-ops": "career",
        "homelab": "homelab",
        "infra": "infra",
        "infrastructure": "infra",
        "down": "down",
        "auto_fix": "auto_fix",
        "doctor": "doctor",
        "briefing": "briefing",
    }
    parts = args.split(maxsplit=1)
    if parts and parts[0] in ("--category", "-c") and len(parts) > 1:
        cat_parts = parts[1].split(maxsplit=1)
        category = cat_parts[0].lower()
        if category not in category_map:
            return {"text": f"❌ Unknown category: {category}. Try: career, homelab, infra"}
        args = cat_parts[1] if len(cat_parts) > 1 else ""
    elif parts and parts[0] in ("--broadcast", "-b"):
        broadcast = True
        args = parts[1] if len(parts) > 1 else ""

    text = args.strip()
    if not text:
        return {"text": "❌ No message text provided"}

    payload = {"text": f"📣 {text}"}
    if category:
        payload["category"] = category_map[category]
    elif broadcast:
        payload["category"] = "broadcast"

    r = _call("/telegram-send", **payload)
    if r.get("status") == "ok":
        target = f"category={category}" if category else ("broadcast" if broadcast else "default channel")
        return {"text": f"📣 Sent to Telegram ({target})."}
    return {"text": "❌ ask: " + str(r.get("error", r))}


@handler("/escalate")
def _sys_escalate(data):
    r = _run_script("human_escalation.py", "--stats", timeout=30)
    if not r["success"]:
        return {"text": "❌ escalate: " + (r["error"] or r["output"])}
    try:
        o = json.loads(r["output"])
        budget = o.get("budget", {})
        text = f"⛑ Escalation stats\nTotal: {o.get('total_escalations', 0)}\n"
        text += f"Budget: {budget.get('max_per_day', '?')}/day, {budget.get('max_per_week', '?')}/week\n"
        decisions = o.get("decisions", {})
        if decisions:
            text += "Decisions: " + ", ".join(f"{k}={v}" for k, v in decisions.items())
        return {"text": text}
    except Exception:
        return {"text": "⛑ Escalation stats\n" + r["output"][:800]}

# ── Deploy / evaluation orchestration ───────────────────────────────────────
# Lets Hermes (or a human via Telegram) deploy a throwaway container that is
# immediately tracked by the inventory self-heal system: labeled
# `homelab.eval=true` (never drift-flagged, never auto-removed until TTL),
# verified running before replying, and surfaced via /evals. Safer than freehand
# `/run docker run ...` because it enforces tracking + TTL + verification.

@handler("/deploy")
def handle_deploy(data):
    rest = (data.get("args") or "").strip()
    if not rest:
        return {"text": "🚀 Usage: /deploy <image> [--name X] [--env K=V] [--port h:c]"}
    tokens = rest.split()
    image = tokens[0]
    if not re.fullmatch(r"[A-Za-z0-9][\w./\-:]+", image):
        return {"text": f"❌ invalid image: {image}"}
    opts = {"name": None, "env": [], "ports": [], "cmd": []}
    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t == "--" and i + 1 < len(tokens):
            opts["cmd"] = tokens[i + 1:]; break
        if t == "--name" and i + 1 < len(tokens):
            opts["name"] = tokens[i + 1]; i += 2
        elif t == "--env" and i + 1 < len(tokens):
            opts["env"].append(tokens[i + 1]); i += 2
        elif t == "--port" and i + 1 < len(tokens):
            opts["ports"].append(tokens[i + 1]); i += 2
        else:
            return {"text": f"❌ unknown option `{t}`"}
    vals = [x for x in (opts["env"] + opts["ports"] + [opts["name"] or ""]) if x]
    if any(not re.fullmatch(r"[A-Za-z0-9_.\-]+", x) for x in vals):
        return {"text": "❌ --name/--env/--port values contain invalid characters"}
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", image)[:30]
    name = opts["name"] or f"eval-{slug}-{int(time.time()) % 100000}"
    cmd = ["docker", "run", "-d", "--name", name, "--label", "homelab.eval=true"]
    for e in opts["env"]:
        cmd += ["-e", e]
    for p in opts["ports"]:
        cmd += ["-p", p]
    cmd += [image] + opts["cmd"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not r.stdout.strip():
        return {"text": f"❌ deploy failed: {(r.stderr or r.stdout or 'unknown').strip()[:200]}"}
    # verify running within a short grace window before reporting back
    deadline = time.time() + 20; state = "created"; hp = "no-healthcheck"
    while time.time() < deadline:
        rr = subprocess.run(["docker", "inspect", "-f",
                             "{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}", name],
                            capture_output=True, text=True, timeout=10)
        o = rr.stdout.strip()
        if o and o.split("|", 1)[0].strip() == "true":
            state = "running"; hp = o.split("|", 1)[1].strip() or "no-healthcheck"; break
        state = o.split("|", 1)[0].strip() if o else "created"
        time.sleep(2)
    if state != "running":
        return {"text": f"⚠️ `{name}`: started but not running ({state}). "
                        "Inventory timer will re-verify next cycle."}
    return {"text": f"✅ deployed `{name}` ← `{image}`\nrunning · health: {hp}\n"
                    "labeled `homelab.eval=true` · tracked at :9180/inventory.json · "
                    "auto-removed after TTL"}


@handler("/evals")
def handle_evals(data):
    """List active evaluations live from Docker (registry can lag up to 5 min)."""
    rr = subprocess.run(["docker", "ps", "-a", "--filter", "label=homelab.eval=true",
                         "--format", "{{.Names}}\t{{.Status}}"],
                        capture_output=True, text=True, timeout=10)
    rows = [l.split("\t", 1) for l in rr.stdout.strip().splitlines() if l]
    if not rows:
        return {"text": "📭 No active evaluations."}
    lines = [f"  • `{n}` · {s}" for n, s in rows]
    return {"text": f"📋 Active evaluations ({len(rows)}):\n" + "".join(lines)}


@handler("/eval-rm")
def handle_eval_rm(data):
    rest = (data.get("args") or "").strip()
    if not rest:
        return {"text": "🧹 Usage: /eval-rm <container-name>"}
    name = rest.split()[0]
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
        return {"text": f"❌ invalid name: {name}"}
    r = subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        return {"text": f"✅ retired `{name}` (eval removed; drops from registry next cycle)"}
    return {"text": f"❌ remove failed: {(r.stderr or 'unknown').strip()[:200]}"}

# ── Telegram command router (appended to n8n_bridge_server.py) ────────────
# Dispatches human-friendly Telegram text like "/docker", "/restart n8n",
# "/graph", "/deadcode", "/briefing" onto existing bridge handlers.
import re

def _call(handler_name, **kw):
    fn = HANDLERS.get(handler_name)
    if not fn:
        return {"error": f"unknown handler {handler_name}"}
    return fn(kw)

def _first_word(text):
    parts = text.split()
    return parts[0].lower() if parts else ""

def _rest(text):
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""

def _logs(rest):
    if not rest:
        return {"error": "container name required"}
    parts = rest.split()
    container = parts[0]
    tail = parts[1] if len(parts) > 1 and parts[1].isdigit() else None
    kw = {"container": container}
    if tail:
        kw["tail"] = int(tail)
    return _call("/docker-logs", **kw)

# ── result shape helpers ──────────────────────────────────────────────
def ok_result(**kw):
    return {"status": "ok", **kw}

def err_result(msg):
    return {"status": "error", "message": str(msg)}

def _fmt(result, maxlen=3500):
    if isinstance(result, dict):
        if result.get("status") == "error":
            return "\u274c " + str(result.get("message", "failed"))
        if result.get("text"):
            return str(result["text"])[:maxlen]
        if result.get("output"):
            return str(result["output"])[:maxlen]
        if result.get("logs"):
            return str(result["logs"])[:maxlen]
        if result.get("message"):
            return "\u26a0\ufe0f " + str(result["message"])
    return str(result)[:maxlen]



def _help_text():
    return (
        "🤖 *Hermes Telegram commands*\n"
        "`/help` — this list\n"
        "`/status` — hermes service health\n"
        "`/health` — bridge ping\n"
        "`/docker` — running containers\n"
        "`/restart <name>` — restart container\n"
        "`/logs <name> [n]` — container logs\n"
        "`/disk` — disk usage\n"
        "`/backup` — backup status\n"
        "`/metrics` — CPU/mem snapshot\n"
        "`/graph` — code-graph status\n"
        "`/deadcode` — dead code report\n"
        "`/arch` — code-graph architecture\n"
        "`/search <q>` — code-graph search\n"
        "`/impact <files>` — impact of file changes\n"
        "`/briefing` — morning briefing\n"
        "`/alert` — unhealthy containers\n"
        "`/scheduler` — scheduler state\n"
        "`/ledger` — decision ledger\n"
        "`/commitments` — active commitments\n"
        "`/queue` — task queue\n"
        "`/digest` — daily digest\n"
        "`/doctor` — run system doctor\n"
        "`/predict` — show proactive predictions (disk, memory, MCP health)\n"
        "`/memory <q>` — search memory\n"
        "`/proactive` — proactive engine state\n"
        "`/cap` — provider caps\n"
        "`/cost` — cost guard status\n"
        "`/routing [enable|disable <name>]` — provider routing\n"
        "`/ask <msg>` — send a message to Telegram channel\n"
        "`/escalate` — escalation stats\n"
        "`/deploy <image> [--name N] [--env K=V] [--port h:c]` — deploy a tracked eval\n"
        "`/evals` — list active evaluations\n"
        "`/eval-rm <name>` — retire an evaluation early\n"
        "`/proposals` — list pending proposals\n"
        "`/send <id>` — approve and execute a proposal\n"
        "`/skip <id>` — reject a proposal\n"
        "`/run <cmd>` — run a shell command\n"
        "`/claude <task>` — delegate to Claude Code (headless)\n"
        "`/delegate <task>` — alias for /claude\n"
        "`/claude-save-session <topic>` — save context for laptop resumption\n"
        "`/claude-load-session <topic>` — load saved context\n"
        "`/claude-resume-session <topic>` — resume on laptop\n"
        "`/memory <q>` — search episodic memory\n"
        "`/memory scan` — scan for stuck items/todos/decisions\n"
        "`/voice-transcribe <file>` — transcribe audio to text\n"
        "`/compose <goal>` — decompose + dispatch multi-step plan\n"
        "`/habit checkoff <id> <value>` — mark a habit done\n"
        "`/habit prompts` — show today's checklist\n"
        "`/recall <q>` — semantic memory recall\n"
        "`/goals` — show active life goals\n"
    )

def _claude_delegate(task: str, category: str = "infra") -> dict:
    """Run a headless Claude Code session and relay the result to Telegram.

    The task is sent to claude_code_delegate.py which spawns `claude --print`
    with context from shared memory. The result is forwarded to the specified
    Telegram topic (default: infra/7356).
    """
    from shlex import quote
    cmd = (
        f"python3 '{HERMES_HOME}/hermes-agent/scripts/claude_code_delegate.py' "
        f"--task {quote(task)} --mode headless --json"
    )
    r = _call("/run", cmd=cmd, timeout=300)
    if r.get("status") != "ok":
        return {"text": f"❌ Claude Code delegation failed: {r.get('error', r.get('output', 'unknown'))}"}
    try:
        result = json.loads(r.get("output", ""))
    except (json.JSONDecodeError, TypeError):
        return {"text": f"⚠️ Claude Code returned non-JSON:\n{r.get('output','')[:500]}"}

    session_id = result.get("session_id", "?")
    summary = result.get("summary", "")
    status = result.get("status", "unknown")

    # Relay result to Telegram topic
    if summary:
        _call("/telegram-send", text=f"🤖 **Claude Code ({session_id[:8]})**\n{summary}",
              category=category, priority="normal")

    icon = "✅" if status == "completed" else "⚠️" if status == "error" else "⏳"
    return {"text": f"{icon} Claude Code session `{session_id[:8]}`\n\n{summary[:800]}\n\n_Sent to {category} topic._"}

HOP_URL = os.environ.get("HOP_URL", "http://127.0.0.1:8083/v1/chat/completions")
HOP_MODEL = os.environ.get("HOP_MODEL", "magnitude/gemma-4-26b-a4b-it-qat:gguf:q4")

def _md_escape(text: str) -> str:
    """Lightly escape Telegram Markdown punctuation so model output sends cleanly."""
    return re.sub(r"([_*\`\[\](~>#+\-=|{}.!)])", r"\\\1", text)


def _homelab_context() -> str:
    """Best-effort live homelab snapshot for the model prompt. Never raises."""
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        cs = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:2375/v1.40/containers/json", timeout=4).read())
        total = len(cs)
        running = sum(1 for c in cs if c.get("State") == "running")
        unhealthy = sum(1 for c in cs if "unhealthy" in (c.get("Status") or ""))
        gw = next((c.get("Status", "?") for c in cs
                   if "/hermes" in (c.get("Names") or [])), "unknown")
        mem = {}
        for line in open("/proc/meminfo"):
            if line.startswith(("MemTotal", "MemAvailable")):
                k, v = line.split(":", 1)
                mem[k] = int(v.split()[0]) // 1024 // 1024  # kB -> GiB
        used = max(0, mem.get("MemTotal", 0) - mem.get("MemAvailable", 0))
        disk = "?"
        out = subprocess.run(["df", "-h", "/"], capture_output=True,
                             text=True, timeout=4).stdout.splitlines()
        disk = next((ln.split()[4] for ln in out[1:]
                     if len(ln.split()) >= 5), "?")
        hop = "ok"
        try:
            urllib.request.urlopen(
                HOP_URL.replace("/v1/chat/completions", "/health"),
                timeout=3).read()
        except Exception:
            hop = "unreachable"
        return (
            f"Homelab live snapshot ({now}, Rohit's home-hp): "
            f"Docker {running}/{total} running, {unhealthy} unhealthy, "
            f"RAM {used}Gi/{mem.get('MemTotal', 0)}Gi, disk / {disk} used, "
            f"gateway(hermes): {gw}, model gateway(hop): {hop}"
        )
    except Exception:
        return "Homelab snapshot unavailable."


def _magnitude_reply(text: str) -> dict:
    """Sidecar agent reply via tokenjuice-hop. Fast-fail, one retry, live context."""
    try:
        urllib.request.urlopen(
            HOP_URL.replace("/v1/chat/completions", "/health"),
            timeout=3).read()
    except Exception:
        return {"text": "⚠️ The model gateway (hop) is unreachable right now. "
                        "Give it a minute and try again."}
    sys_prompt = (
        "You are Chaguli, the personal homelab assistant for Rohit, "
        "partner to Hermes on the home-hp server (rohitmishra.com).\n"
        f"{_homelab_context()}\n"
        "Rules:\n"
        "- Be brief and direct (1-4 short sentences; greet back in one line).\n"
        "- Answer homelab/container/service/RAM/disk questions using ONLY the "
        "snapshot above - never invent status numbers.\n"
        "- If the snapshot is unavailable or stale, say so instead of guessing.\n"
        "- If asked which model you run on: the 'haiku-4.5' alias on "
        "tokenjuice-hop, which routes to nvidia/minimax-m3 via OmniRoute, with "
        "a local magnitude (Gemma) model as last-resort fallback.\n"
        "- If asked for detail beyond the snapshot, suggest the right Telegram "
        "slash command (e.g. /docker, /disk, /status, /health)."
    )
    payload = json.dumps({
        "model": HOP_MODEL,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": text},
        ],
        "max_tokens": 300,
        "stream": False,
    }).encode()
    req = urllib.request.Request(HOP_URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    last_err = None
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read())
            content = ((data.get("choices") or [{}])[0].get("message", {})
                       .get("content", "") or "").strip()
            if not content:
                raise ValueError("empty model response")
            return {"text": _md_escape(content)[:4000]}
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.5)
    return {"text": f"⚠️ reply failed after 2 attempts "
                    f"({type(last_err).__name__}: {last_err}). "
                    "Hop may be slow - try again in a minute."}




_tg_chat_ctx = {"chat_id": None, "thread_id": None}
_APPLY_QUEUE_RESERVED = {"myworkdayjobs", "linkedin", "indeed", "glassdoor"}


def _clean_job_line(ln: str) -> str:
    """Strip leading command phrase / separators from a pasted job line."""
    out = re.sub(r"(?i)^run\s+the\s+(jobs|job)\s+pipeline\s*[:.-]?\s*", "", ln).strip()
    out = out.strip("|-•:.,")
    return out




def _split_title_company(company: str, title: str) -> tuple:
    """When the company is unknown but the title carries a 'Company - Role' prefix, split it."""
    if company == "Unknown" and title != "Unknown" and " - " in title:
        head, _, rest = title.partition(" - ")
        if head.strip():
            return head.strip()[:80], rest.strip()[:120]
    return company, title


def _extract_job_meta(text: str, url: str) -> tuple:
    """Best-effort company/title from the pasted posting text."""
    t = text.replace(url, " ")
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    company, title = "Unknown", "Unknown"
    for i, ln in enumerate(lines):
        low = ln.lower()
        if not ln or len(ln) > 140 or low in _APPLY_QUEUE_RESERVED or "myworkday" in low:
            continue
        if re.search(r"director|manager|engineer|lead|analyst|specialist|developer|scientist",
                     low, re.I):
            title = _clean_job_line(re.sub(r"[|].*$", "", ln))
            break
    if title == "Unknown":
        for ln in lines[:8]:
            if re.search(r"(?:sr\.?|senior|director|manager|engineer|lead|vp|principal)",
                         ln.lower(), re.I):
                title = _clean_job_line(re.sub(r"[|].*$", "", ln))
                break
    for ln in lines[:10]:
        low = ln.lower()
        if "nasdaq" in low and "(" in ln:
            company = ln.split("(")[0].strip().split(",")[0].strip()
            break
        if low in ("myworkdayjobs",) or low.startswith("fluenc"):
            continue
        if "(" in ln and ")" in ln and not re.search(r"director|manager|engineer|lead", low):
            cand = ln.split("(")[0].strip()
            if 2 < len(cand) < 60:
                company = cand
                break
    return _split_title_company(company, title)




def _fetch_job_meta(url: str, timeout: int = 25) -> tuple:
    """Best-effort company/title pulled from the posting page (JSON-LD, og:title)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
        company, title = "Unknown", "Unknown"
        for m in re.finditer(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", raw, re.S | re.I):
            try:
                data = json.loads(m.group(1))
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for it in items:
                tpe = it.get("@type")
                typs = tpe if isinstance(tpe, list) else ([tpe] if tpe else [])
                if "JobPosting" not in typs:
                    continue
                if title == "Unknown" and it.get("title"):
                    title = _clean_job_line(str(it["title"]))
                ho = it.get("hiringOrganization") or {}
                if company == "Unknown" and isinstance(ho, dict) and ho.get("name"):
                    c = re.sub(r"\s*,?\s*(llc|inc|corp|ltd|limited|gmbh|sa|ag|plc)\s*$",
                                "", str(ho["name"]), flags=re.I).strip().strip(",").strip()
                    if c:
                        company = c
        if company == "Unknown":
            osn = re.search(r'property="og:site_name" content="(.*?)"', raw, re.I)
            if osn:
                c = html.unescape(osn.group(1)).strip()
                if c:
                    company = c[:80]
        if title == "Unknown":
            og = re.search(r'property="og:title" content="(.*?)"', raw, re.I)
            if og:
                title = _clean_job_line(html.unescape(og.group(1)))
        if title == "Unknown":
            tm = re.search(r"<title>(.*?)</title>", raw, re.S | re.I)
            if tm:
                title = _clean_job_line(html.unescape(tm.group(1)))
        return _split_title_company(company, title)
    except Exception:
        return "Unknown", "Unknown"


def _queue_apply(url: str, company: str, title: str) -> bool:
    """Write an apply request the host-side worker picks up (real host paths + creds)."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        base = os.path.dirname(here)  # scripts/ .. = /opt/data or /home/rohit/.hermes
        qdir = os.path.join(base, "data", "apply_queue")
        os.makedirs(qdir, exist_ok=True)
        rid = hashlib.sha1(url.encode()).hexdigest()[:12]
        req = {
            "id": rid,
            "url": url,
            "company": company,
            "title": title,
            "score": 0,
            "bypass_score": True,
            "chat_id": _tg_chat_ctx.get("chat_id"),
            "thread_id": _tg_chat_ctx.get("thread_id"),
            "ts": round(time.time()),
        }
        path = os.path.join(qdir, rid + ".json")
        if os.path.exists(path):
            return True
        with open(path, "w") as fh:
            json.dump(req, fh, indent=2)
        return True
    except Exception:
        return False


def _run_jobs_pipeline(text=None) -> dict:
    """Run the Hermes job pipeline; if a URL is pasted, also queue a host-side apply."""
    text = (text or "").strip()
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, "auto_pipeline.py")
    if not os.path.exists(script):
        return {"text": "pipeline script not found"}
    if _tg_chat_ctx.get("chat_id"):
        try:
            _telegram_send_text(_tg_chat_ctx["chat_id"],
                "⏳ Running the jobs pipeline \u2014 discovery digest first, then the apply is queued for host execution.",
                message_thread_id=_tg_chat_ctx.get("thread_id"))
        except Exception:
            pass
    try:
        r = subprocess.run([sys.executable, script, "--no-telegram"],
                           capture_output=True, text=True, timeout=300,
                           cwd=here)
    except subprocess.TimeoutExpired:
        return {"text": "jobs pipeline timed out after 5 min. Try again."}
    except Exception as e:
        return {"text": "jobs pipeline error: %s" % e}
    out = r.stdout or ""
    if r.returncode != 0 and r.stderr:
        out += ("\n[stderr] " + r.stderr[-500:])
    lines = out.splitlines()
    markers = [i for i, l in enumerate(lines) if l.strip().startswith("---- DIGEST")]
    body = ("\n".join(lines[markers[-1] + 1:]) if markers else out).strip() or "pipeline produced no digest"
    m = re.search(r"https?://[^\s]+", text)
    if m:
        url = m.group(0)
        company, title = _extract_job_meta(text, url)
        if "Unknown" in company or "Unknown" in title:
            fc, ft = _fetch_job_meta(url)
            company = fc if "Unknown" in company else company
            title = ft if "Unknown" in title else title
        if _queue_apply(url, company, title):
            body = (body[:2800] + "\n\n📬 Queued apply for host execution:\n• %s\n• %s" % (title, company))
        else:
            body = (body[:2800] + "\n\n⚠️ Could not queue the provided link for apply.")
    return {"text": body[:4000]}


def _route_telegram_command(text):
    text = (text or "").strip()
    if not text:
        return {"text": _help_text()}
    cmd = _first_word(text)
    rest = _rest(text)
    m = {
        "/help": lambda: {"text": _help_text()},
        "/status": lambda: _call("/system-health"),
        "/health": lambda: _call("/health-ping"),
        "/docker": lambda: _call("/docker-ps"),
        "/restart": lambda: _call("/docker-restart", container=rest) if rest else {"error": "container name required"},
        "/logs": lambda: _logs(rest),
        "/disk": lambda: _call("/disk-usage"),
        "/backup": lambda: _call("/backup-status"),
        "/metrics": lambda: _call("/metrics"),
        "/graph": lambda: _call("/code-graph/status"),
        "/deadcode": lambda: _call("/code-graph/dead-code"),
        "/arch": lambda: _call("/code-graph/architecture"),
        "/search": lambda: _call("/code-graph/search", q=rest) if rest else {"error": "search term required"},
        "/impact": lambda: _call("/code-graph/impact", files=rest) if rest else {"error": "files required"},
        "/briefing": lambda: handle_morning_briefing({}),
        "/jobpipeline": lambda: _run_jobs_pipeline(),
        "/pipeline": lambda: _run_jobs_pipeline(),
        "/alert": lambda: _call("/docker-unhealthy"),
         "/scheduler": lambda: _call("/all-services-status"),
         "/run": lambda: _call("/run", cmd=rest, timeout=30) if rest else {"error": "cmd required"},
         "/ledger": lambda: _call("/ledger", args=rest),
         "/commitments": lambda: _call("/commitments", args=rest),
         "/queue": lambda: _call("/queue", args=rest),
         "/digest": lambda: _call("/digest", args=rest),
         "/doctor": lambda: _call("/doctor", args=rest),
         "/memory": lambda: _call("/memory", args=rest) if rest else {"error": "query required: /memory <query>"},
         "/predict": lambda: _call("/predict"),
         "/proactive": lambda: _call("/proactive", args=rest),
         "/cap": lambda: _call("/cap", args=rest),
         "/cost": lambda: _call("/cost", args=rest),
 
        "/jobs-latest": lambda: _call("/jobs-latest", args=rest),
        "/providers-status": lambda: _call("/providers-status", args=rest),
        "/provider-status": lambda: _call("/providers-status", args=rest),
        "/routing": lambda: _call("/routing", args=rest) if rest else _call("/routing", args="status"),
        "/ask": lambda: _call("/ask", args=rest) if rest else {"error": "message required: /ask <message>"},
        "/escalate": lambda: _call("/escalate", args=rest),
        "/deploy": lambda: _call("/deploy", args=rest) if rest else {"error": "image required: /deploy <image>"},
        "/evals": lambda: _call("/evals"),
        "/eval-rm": lambda: _call("/eval-rm", args=rest) if rest else {"error": "name required: /eval-rm <name>"},
        "/recall": lambda: _route_recall(rest),
        "/goals": lambda: _route_goals(),
        "/send": lambda: _call("/send", args=rest) if rest else {"text": "❌ Usage: /send <proposal_id>"},
        "/skip": lambda: _call("/skip", args=rest) if rest else {"text": "❌ Usage: /skip <proposal_id>"},
        "/proposals": lambda: _call("/proposals"),
        "/claude": lambda: _claude_delegate(rest, category="infra") if rest else {"text": "Usage: /claude <task>\nDelegates to Claude Code (headless). Results sent to Infra topic."},
        "/delegate": lambda: _claude_delegate(rest, category="infra") if rest else {"text": "Usage: /delegate <task>\nAlias for /claude."},
        "/habit": lambda: _call("/habit", args=rest) if rest else {"text": "Usage: /habit checkoff <id> <value> | /habit prompts | /habit summaries"},
        "/habits": lambda: _call("/habit", args="streaks"),
        "/memory": lambda: _call("/memory", args=rest) if rest else {"text": "Usage: /memory scan | /memory notify"},
        "/voice-transcribe": lambda: _call("/voice-transcribe", args=rest) if rest else {"text": "Usage: /voice-transcribe <file> [--backend google-free]"},
        "/compose": lambda: _call("/compose", args=rest) if rest else {"text": "Usage: /compose <goal>"},
        "/compose-dry": lambda: _call("/compose", args=rest, dry_run=True) if rest else {"text": "Usage: /compose-dry <goal>"},
        "/claude-save-session": lambda: _call("/claude-save-session", args=rest) if rest else {"text": "Usage: /claude-save-session <topic>"},
        "/claude-load-session": lambda: _call("/claude-load-session", args=rest) if rest else {"text": "Usage: /claude-load-session <topic>"},
        "/claude-resume-session": lambda: _call("/claude-resume-session", args=rest) if rest else {"text": "Usage: /claude-resume-session <topic>"},
    }
    handler_fn = m.get(cmd)
    if not handler_fn:
        if not cmd.startswith("/"):
            # Sidecar agent path: plain (non-command) text goes to the local model.
            _low = text.lower()
            if "jobs pipeline" in _low or "job pipeline" in _low:
                return _run_jobs_pipeline(text)
            return _magnitude_reply(text)
        return {"text": f"Unknown command `{cmd}`. Try `/help`."}
    try:
        result = handler_fn()
    except Exception as e:
        return {"text": f"⚠️ error: {e}"}
    return {"text": _fmt(result)}


def _route_recall(query: str) -> dict:
    """Semantic search over Hermes' episodic memory — closes cross-cycle recall loop."""
    if not query:
        return {"error": "usage: /recall <search term>"}
    try:
        HERMES_HOME = Path.home() / ".hermes"
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import narrative_memory as _nm
        results = _nm.retrieve_similar(query, k=5)
        if not results:
            return {"text": f"🔍 No memory matches for '{query}'."}
        lines = [f"🔍 **Memory recall for:** {query}", ""]
        for r in results:
            ts = r.get("ts", "")[:10]
            lines.append(f"• [{ts}] {r.get('content', '')[:120]}")
        return {"text": "\n".join(lines[:12])}
    except Exception as e:
        return {"text": f"⚠️ recall error: {e}"}


def _route_goals():
    """Show active life goals from personal_model."""
    try:
        HERMES_HOME = Path.home() / ".hermes"
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import personal_model as _pm
        pm = _pm._load_state()
        goals = pm.get("life_goals", [])
        if not goals:
            return {"text": "🎯 No active life goals. Personal model not yet initialised."}
        lines = ["🎯 **Active Life Goals**", ""]
        for g in goals:
            lines.append(f"• **[{g.get('priority',0)}]** {g.get('title','')} `{g.get('domain','')}`")
            for m in g.get("milestones", [])[:2]:
                lines.append(f"  - {m}")
        return {"text": "\n".join(lines[:25])}
    except Exception as e:
        return {"text": f"⚠️ goals error: {e}"}

@handler("/memory-write")
def handle_memory_write(data):
    """Persist an LLM reply into Hermes memory (trusted bridge callers only).

    Accepts: {text, namespace?, key?, domain?, tags?}
    Writes via `unified_memory.py store` as the owning user (rohit).
    """
    text = str(data.get("text") or "").strip()
    if not text:
        return {"error": "text is required"}
    namespace = str(data.get("namespace") or "jarvis")
    key = str(data.get("key") or hashlib.sha1(text.encode("utf-8", "replace")).hexdigest())
    domain = str(data.get("domain") or "JARVIS")
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    args = ["store", namespace, key, text, "--domain", domain, "--tags", *tags]
    try:
        pr = subprocess.run(
            ["sudo", "-n", "env", "HOME=/home/rohit", sys.executable,
             str(_HH / "scripts" / "unified_memory.py"), *args],
            capture_output=True, text=True, timeout=30, cwd="/home/rohit",
        )
        r = {"success": pr.returncode == 0, "output": pr.stdout[-3000:],
             "error": pr.stderr[-500:], "code": pr.returncode}
    except subprocess.TimeoutExpired:
        r = {"success": False, "output": "", "error": "timed out", "code": -1}
    except Exception as e:
        r = {"success": False, "output": "", "error": str(e), "code": -1}
    if r["success"]:
        return {"stored": True, "id": f"{namespace}/{key}", "domain": domain}
    return {"stored": False, "error": r["error"] or r["output"]}


@handler("/cmd")
def handle_cmd(data):
    return {"status": "ok", "result": _route_telegram_command(data.get("text", ""))}

if __name__ == "__main__":
    main()
