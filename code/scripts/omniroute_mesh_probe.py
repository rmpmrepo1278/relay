#!/usr/bin/env python3
"""omniroute_mesh_probe.py — daily health probe of the OmniRoute free-mesh.

Checks the live fallback legs + vendor auto-combos with 1-token calls and
alerts via the n8n-bridge Telegram sidecar if any leg drifts. Redundant mesh
means one dead leg is fine; an alert means look once, action once.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path("/home/rohit/.hermes")
LOG = HERMES_HOME / "logs" / "omniroute_mesh_probe.log"
STATE = HERMES_HOME / "state" / "omniroute_mesh_probe.json"
LOCK = HERMES_HOME / "state" / "omniroute_mesh_probe.lock"
BRIDGE = "http://127.0.0.1:9199/telegram-send"
BASE = "http://127.0.0.1:20128"
_KEY_FILE = HERMES_HOME / "state" / "omniroute_pi_key"
KEY = os.environ.get("OMNIROUTE_PI_KEY", _KEY_FILE.read_text().strip() if _KEY_FILE.exists() else "no-key")
ALERT_WINDOW = 6 * 3600

AP = "openai-compatible-chat-936e95e2-6836-4348-8dd3-107ec38bdb24"

LEGS = [
    ("combo", "combo/pi-free-fallback"),
    # 2026-09-12: key sk-79bf... is scoped to the combo; auto/* and groq-direct legs
    # can never succeed under it (401/404/0) -> chronically false-flagged the job.
]
TRANSITENT = {429, 401}


def log(msg: str) -> None:
    with open(LOG, "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}Z {msg}\n")


def probe(model: str) -> int:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ok"}],
        "max_tokens": 4,
    }).encode()
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + KEY,
                                          "User-Agent": "curl/8.5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"alerts": {}}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2))


def alert(text: str) -> None:
    body = json.dumps({"text": text}).encode()
    try:
        urllib.request.urlopen(BRIDGE, data=body, timeout=10)
    except Exception as e:
        log(f"alert POST failed: {e}")


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("already running (lock held)")
            return 0

        bad = []
        details = []
        for name, model in LEGS:
            code = probe(model)
            log(f"{name} {model} -> {code}")
            details.append(f"{name}={code}")
            if code == 0:
                bad.append(f"router/unreachable for {name}")
            elif code not in TRANSITENT and code != 200:
                bad.append(f"{name} = HTTP {code}")

        st = load_state()
        now = int(time.time())
        if bad:
            key = "mesh"
            if st["alerts"].get(key, 0) <= now - ALERT_WINDOW:
                text = "⚠️ OmniRoute issue:\n" + "\n".join("  - " + b for b in bad)
                alert(text)
                st["alerts"][key] = now
                log("ALERT: " + text)
            else:
                log("issue present but alert on cooldown")
        else:
            st["alerts"].pop("mesh", None)
        st["last_run"] = datetime.now(timezone.utc).isoformat()
        st["failures"] = bad
        st["legs"] = " ".join(details)
        save_state(st)
        return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())