#!/usr/bin/env python3
"""agent_manager.py — Safe spawn/retire of specialized agents.

Jenny has authority to grow/shrink the team. To stay safe, LLM output is ONLY
used for name/role/triggers — never code. New agents get:

  agents/<name>.py          — generic watchdog domain script (check/report)
  agentbus/memory/<name>.md — personality playbook (Identity/Role/Triggers/Exits)
  systemd unit agent-<name>.service  ->  runs agent_loop.py <name>

Spawn rules enforced here (hard safety):
  * name must be ^[a-z][a-z0-9_]{1,19}$
  * name must not collide with existing agents or protected core names
  * role/triggers sanitized (plain text, no shell metacharacters)
Retire:
  * rejects protected core agents unless force=True
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

HERMES_HOME = Path(os.path.expanduser("~/.hermes"))
AGENTS_DIR = HERMES_HOME / "agents"
MEMORY_DIR = HERMES_HOME / "agentbus" / "memory"
UNIT_DIR = Path(os.path.expanduser("~/.config/systemd/user"))
LOOP_PY = AGENTS_DIR / "agent_loop.py"
TEMPLATE_PY = Path(__file__).parent / "_watchdog_agent_template.py"

PROTECTED = {"jenny", "homelab", "baseplate", "vault", "courier", "inference",
             "finlay", "housekeep", "calendula", "connector"}

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,19}$")
SHELL_BAD = re.compile(r"[;&|$`\\\n\r<>()]")


def _safe_text(s: str, maxlen: int = 200) -> str:
    s = (s or "").strip()
    s = SHELL_BAD.sub(" ", s)
    return s[:maxlen]


def _list_agents() -> list[str]:
    names = []
    for p in AGENTS_DIR.glob("*.py"):
        if p.name not in ("agent_loop.py", "agent_frame.py"):
            names.append(p.stem)
    return sorted(set(names) | PROTECTED)


def _publish_presence(name: str, kind: str, note: str = ""):
    import urllib.request
    payload = json.dumps({"agent": name, "kind": kind, "note": note[:120]}).encode()
    req = urllib.request.Request("http://127.0.0.1:9107/presence", data=payload,
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass


# ─── Domain script template (placeholders: __NAME__, __NAME_JSON__,
#     __ROLE_JSON__, __TRIGGERS_JSON__) ───────────────────────────────────────


def _watchdog_script(name: str, role: str, triggers: list[str]) -> str:
    src = TEMPLATE_PY.read_text()
    return (src
            .replace("__NAME__", name)
            .replace("__NAME_JSON__", json.dumps(name))
            .replace("__ROLE_JSON__", json.dumps(role))
            .replace("__TRIGGERS_JSON__", json.dumps(triggers)))


# ─── Spawn / Retire ──────────────────────────────────────────────────────────

def spawn_agent(name: str, role: str, triggers: list[str] | None = None) -> dict:
    name = (name or "").strip().lower()
    role = _safe_text(role, 200)
    triggers = [_safe_text(t, 40) for t in (triggers or []) if _safe_text(t, 40)]
    if not NAME_RE.match(name):
        return {"ok": False, "error": "invalid name '%s' (need ^[a-z][a-z0-9_]{1,19}$)" % name}
    if name in PROTECTED:
        return {"ok": False, "error": "'%s' is a protected core agent" % name}
    if name in _list_agents():
        return {"ok": False, "error": "agent '%s' already exists" % name}
    if not role:
        return {"ok": False, "error": "role required"}

    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    trigger_lines = "\n".join("- %s" % t for t in triggers) if triggers else "- follow playbook priorities"
    personality = """# %s

## Identity
You are `%s`, a specialized homelab agent managed by Jenny (Chief of Staff).
Role: %s

## Core Responsibilities
- %s
- report findings to the bus board; escalate blocked/uncertain items

## Triggers
%s

## Playbook Priorities
- run `check` every cycle to surface new items
- post ready tasks via `report` when something needs human attention
- keep entries in store.json so work is persistent and shared

## Evolution Log
- %s: spawned by Jenny
""" % (name, name, role, role, trigger_lines, date.today().isoformat())
    (MEMORY_DIR / ("%s.md" % name)).write_text(personality)

    (AGENTS_DIR / ("%s.py" % name)).write_text(_watchdog_script(name, role, triggers))

    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    unit = """[Unit]
Description=Autonomous agent loop - %s
After=network.target agentbus.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 %s %s --interval 300
Restart=on-failure
RestartSec=30
Environment=AGENTBUS_URL=http://127.0.0.1:9107
Environment=HOP_URL=http://127.0.0.1:8083/v1/chat/completions
Environment=HOP_MODEL=haiku-4.5

[Install]
WantedBy=default.target
""" % (name, LOOP_PY, name)
    (UNIT_DIR / ("agent-%s.service" % name)).write_text(unit)

    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=10)
    r = subprocess.run(["systemctl", "--user", "start", "agent-%s.service" % name],
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        return {"ok": False, "error": "systemd start failed: %s" % r.stderr[:200],
                "created_files": True}

    _publish_presence(name, "up")
    return {"ok": True, "agent": name, "role": role,
            "service": "agent-%s.service" % name,
            "personality": str(MEMORY_DIR / ("%s.md" % name))}


def retire_agent(name: str, reason: str = "", force: bool = False) -> dict:
    name = (name or "").strip().lower()
    if not NAME_RE.match(name):
        return {"ok": False, "error": "invalid name '%s'" % name}
    if name in PROTECTED and not force:
        return {"ok": False, "error": "'%s' is protected; refusing to retire" % name}
    unit = UNIT_DIR / ("agent-%s.service" % name)
    if not unit.exists():
        return {"ok": False, "error": "no unit for '%s' (not a managed agent)" % name}

    notes = _safe_text(reason or "retired by Jenny (under-used / replaced)", 200)

    subprocess.run(["systemctl", "--user", "stop", "agent-%s.service" % name], capture_output=True, timeout=20)
    subprocess.run(["systemctl", "--user", "disable", "agent-%s.service" % name], capture_output=True, timeout=20)

    if (AGENTS_DIR / ("%s.py" % name)).exists():
        os.replace(AGENTS_DIR / ("%s.py" % name), AGENTS_DIR / ("%s.py.retired" % name))
    if (MEMORY_DIR / ("%s.md" % name)).exists():
        os.replace(MEMORY_DIR / ("%s.md" % name), MEMORY_DIR / ("%s.retired.md" % name))

    _publish_presence(name, "idle", notes[:120])
    return {"ok": True, "agent": name, "reason": notes, "archived": True}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: agent_manager.py spawn <name> <role> [trigger,...] | retire <name> [reason]")
        sys.exit(1)
    op = sys.argv[1]
    if op == "spawn":
        name = sys.argv[2]
        role = sys.argv[3] if len(sys.argv) > 3 else ""
        triggers = sys.argv[4].split(",") if len(sys.argv) > 4 else []
        print(json.dumps(spawn_agent(name, role, triggers), indent=2))
    elif op == "retire":
        name = sys.argv[2]
        reason = " ".join(sys.argv[3:])
        print(json.dumps(retire_agent(name, reason), indent=2))