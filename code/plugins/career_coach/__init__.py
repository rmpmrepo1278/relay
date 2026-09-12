"""Career Coach Plugin — pre_gateway_dispatch hook (dormant, activates on gateway reload).

Routes /story, /mock, /coach, /linkedin, /career messages to the host-side career_coach.py
CLI via SSH and returns results to the same chat/thread — deterministic, without the LLM.

Primary path today is the Hermes skill bundle (skills/career-ops/career-ops-bundle/career-coach.md);
this hook is the deterministic fallback once the gateway reloads and discovers this plugin.
"""

import json
import logging
import os
import re
import subprocess
import threading
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

COACH_REMOTE = "rohit@127.0.0.1"
SSH_KEY = "/opt/data/.ssh/id_ed25519"
TIMEOUT = 120
_STORY_FIELDS = ["title", "situation", "task", "action", "result", "metrics"]

_SSH_BASE = [
    "ssh",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "ConnectTimeout=10",
    "-i", SSH_KEY,
    COACH_REMOTE,
]

_COMMANDS = ("/story", "/mock", "/coach", "/linkedin", "/career")

_CAPTURE_SESSIONS: Dict[str, list] = {}
_MOCK_SESSIONS: Dict[str, str] = {}


def _ssh_command(cmd: str, timeout: int = TIMEOUT) -> str:
    try:
        result = subprocess.run(
            list(_SSH_BASE) + [cmd], capture_output=True, text=True, timeout=timeout)
        return (result.stdout or "") + ("\n" + (result.stderr or ""))
    except subprocess.TimeoutExpired:
        return "Coach timed out after %ds" % timeout
    except Exception as e:  # noqa: BLE001
        return f"Coach error: {e}"


def _write_host_file(host_path: str, content: str) -> None:
    import base64
    b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    _ssh_command(f"echo {b64} | base64 -d > {host_path}", timeout=30)


def _run_coach(args: str) -> str:
    return _ssh_command(f"cd /home/rohit/.hermes/scripts && python3 career_coach.py {args}")


def _env_creds() -> tuple:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel = os.environ.get("TELEGRAM_HOME_CHANNEL", "")
    env_path = os.path.join(os.path.expanduser("~"), ".hermes", ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                token = token or line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("TELEGRAM_HOME_CHANNEL="):
                channel = channel or line.split("=", 1)[1].strip().strip('"').strip("'")
    return token, channel


def _source_addr(source: Any) -> tuple:
    chat_id = ""
    thread_id = None
    if source:
        chat_id = str(getattr(source, "chat_id", None) or "")
        raw = getattr(source, "thread_id", None)
        if raw not in (None, "", "1"):
            thread_id = str(raw)
    if not chat_id:
        _, channel = _env_creds()
        chat_id, _, tid = channel.partition(":")
        thread_id = thread_id or (tid if tid and tid != "1" else None)
    return chat_id, thread_id


def _send_telegram(token: str, chat_id: str, thread_id: Optional[str], text: str) -> None:
    if not token or not chat_id or not text:
        return
    payload = {"chat_id": chat_id, "text": text[:4000], "parse_mode": "Markdown"}
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                logger.warning("career_coach: telegram send failed: %s", result)
    except Exception as e:  # noqa: BLE001
        logger.warning("career_coach: telegram send error: %s", e)


def _send(chat_id: str, thread_id: Optional[str], text: str) -> None:
    token, _ = _env_creds()
    if chat_id and token:
        _send_telegram(token, chat_id, thread_id, text)


def _pretty(json_text: str) -> str:
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return json_text.strip()[:2000]
    if isinstance(data, dict):
        lines = []
        for k, v in data.items():
            if isinstance(v, dict):
                for kk, vv in v.items():
                    lines.append(f"• {kk}: {vv}")
            elif isinstance(v, list):
                lines.append(f"• {k}: " + " | ".join(str(x) for x in v))
            else:
                lines.append(f"• {k}: {v}")
        return "\n".join(lines)[:2000]
    return str(data)[:2000]


def _COMPETENCY(arg: str) -> str:
    mapping = {
        "program": "Program Strategy & Portfolio", "strategy": "Program Strategy & Portfolio",
        "delivery": "Delivery at Scale", "scale": "Delivery at Scale",
        "stakeholder": "Stakeholder & Executive Communication", "exec": "Stakeholder & Executive Communication",
        "steerco": "Stakeholder & Executive Communication",
        "financial": "Financial & Commercial", "budget": "Financial & Commercial", "commercial": "Financial & Commercial",
        "risk": "Risk, Dependency & Governance", "governance": "Risk, Dependency & Governance",
        "leadership": "Leadership & Talent", "talent": "Leadership & Talent",
    }
    return mapping.get(arg.lower(), "generic")


def on_pre_gateway_dispatch(event: Any, **kwargs) -> Optional[Dict[str, Any]]:
    text = (getattr(event, "text", "") or "")
    cleaned = text.strip()
    if not cleaned:
        return None
    source = getattr(event, "source", None)
    chat_id, thread_id = _source_addr(source)
    chat_key = chat_id or "default"

    if chat_key in _CAPTURE_SESSIONS:
        fields = _CAPTURE_SESSIONS[chat_key]
        fields.append(cleaned)
        if len(fields) >= 6:
            del _CAPTURE_SESSIONS[chat_key]
            payload = json.dumps(dict(zip(_STORY_FIELDS, fields)), ensure_ascii=False)
            host_file = f"/tmp/coach_story_{abs(hash(fields[0])) % 10**6}.json"
            _write_host_file(host_file, payload)
            result = _run_coach(f"add --json-file {host_file}")
            thread = threading.Thread(
                target=lambda: _send(chat_id, thread_id, _pretty(result)),
                daemon=True)
            thread.start()
        else:
            next_field = _STORY_FIELDS[len(fields)]
            _send(chat_id, thread_id, f"Next: **{next_field.upper()}** — send it along.")
        return {"action": "skip", "reason": "career_coach: capture step"}

    if chat_key in _MOCK_SESSIONS:
        comp = _MOCK_SESSIONS.pop(chat_key)
        result = _run_coach(f"score --text \"{cleaned.replace(chr(34), chr(39))}\" --competency \"{comp}\"")
        _send(chat_id, thread_id, _pretty(result))
        return {"action": "skip", "reason": "career_coach: mock answer scored"}

    if not cleaned.startswith(_COMMANDS):
        return None

    words = cleaned.split()
    cmd = words[0].lower()
    arg = " ".join(words[1:])

    def _dispatch():
        result = ""
        if cmd == "/story":
            sub = arg.split()[0] if arg.split() else ""
            if sub in ("", "new"):
                _CAPTURE_SESSIONS[chat_key] = []
                result = ("Guided capture: send **{title}**, then **situation**, **task**, **action**, **result**, "
                          "**metrics/tags** — one message per field. Start with your story's headline.")
            elif sub == "list":
                result = _run_coach("list")
            elif sub == "show":
                result = _run_coach(f"show {arg.split()[1] if len(arg.split()) > 1 else ''}".rstrip(" "))
            elif sub == "refine":
                parts = arg.split()
                result = (_run_coach(f"refine {parts[1]} --field {parts[3]} --value {parts[5]}")
                          if len(parts) >= 6 else "usage: /story refine <id> --field <f> --value <v>")
            else:
                result = "usage: /story [new|list|show <id>|refine <id> --field <f> --value <v>]"
        elif cmd == "/mock":
            comp = _COMPETENCY(arg)
            _MOCK_SESSIONS[chat_key] = comp
            result = _run_coach(f"question --competency \"{comp}\"")
        elif cmd == "/coach":
            result = (_run_coach(f"score --text \"{arg.replace(chr(34), chr(39))}\"")
                      if arg else "Paste the answer text after /coach to be scored.")
        elif cmd == "/linkedin":
            result = _run_coach("linkedin")
        elif cmd == "/career":
            result = _run_coach("weekly")
            stories = _run_coach("list")
            if stories.strip():
                result += "\n\n" + stories[:1000]
        _send(chat_id, thread_id, _pretty(result))

    threading.Thread(target=_dispatch, daemon=True).start()
    return {"action": "skip", "reason": "career_coach: command handled (async)"}


def register(ctx: Any) -> None:
    ctx.register_hook("pre_gateway_dispatch", on_pre_gateway_dispatch)
    import sys
    print("✅ career_coach plugin loaded: pre_gateway_dispatch hook registered", file=sys.stderr, flush=True)
    logger.info("career_coach: registered pre_gateway_dispatch hook")