#!/usr/bin/env python3
"""Host-side apply queue worker for AgentChaguli.

Picks up job-apply requests written into /home/rohit/.hermes/data/apply_queue/
(by the n8n-bridge container or the discovery pipeline) and runs the real
career-ops apply via run_apply.sh which owns host paths, creds and GDrive push.
Results are posted back to the Telegram thread that requested them.
"""
import base64
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path


def _env(key, default):
    return os.environ.get(key, default)


QUEUE = Path(_env("APPLY_QUEUE_DIR", "/home/rohit/.hermes/data/apply_queue"))
DONE = QUEUE / "done"
FAIL = QUEUE / "failed"
BRIDGE = _env("BRIDGE_URL", "http://127.0.0.1:9199/telegram-send")
RUN_APPLY = Path(_env("RUN_APPLY_SHIM", "/home/rohit/.hermes/scripts/run_apply.sh"))


def post(text, chat_id, thread_id):
    try:
        payload = {"text": text, "chat_id": chat_id, "category": "career"}
        if thread_id:
            payload["message_thread_id"] = thread_id
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            BRIDGE, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:  # noqa: BLE001
        print("[post] error:", e)


def main():
    DONE.mkdir(parents=True, exist_ok=True)
    FAIL.mkdir(parents=True, exist_ok=True)
    for job in sorted(QUEUE.glob("*.json")):
        try:
            req = json.loads(job.read_text())
        except Exception as e:  # noqa: BLE001
            print("[skip] unreadable", job.name, e)
            job.replace(FAIL / job.name)
            continue

        title = req.get("title", "Unknown")
        company = req.get("company", "Unknown")
        payload = json.dumps({
            "url": req.get("url", ""),
            "company": company,
            "title": title,
            "score": int(req.get("score", 0) or 0),
            "bypass_score": bool(req.get("bypass_score", False)),
        }).encode()
        b64 = base64.b64encode(payload).decode()

        try:
            r = subprocess.run(["bash", str(RUN_APPLY), b64],
                               capture_output=True, text=True, timeout=600)
            tail = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
            tail = "\n".join(tail.strip().splitlines()[-12:])[:3500]
            post("🤖 Apply result · %s @ %s (rc=%s):\n%s"
                 % (title, company, r.returncode, tail),
                 req.get("chat_id"), req.get("thread_id"))
            job.replace(DONE / job.name)
        except subprocess.TimeoutExpired:
            post("⚠️ Apply timed out · %s @ %s (10 min)" % (title, company),
                 req.get("chat_id"), req.get("thread_id"))
            job.replace(FAIL / job.name)
        except Exception as e:  # noqa: BLE001
            post("⚠️ Apply failed · %s @ %s: %s" % (title, company, e),
                 req.get("chat_id"), req.get("thread_id"))
            job.replace(FAIL / job.name)
        time.sleep(2)


if __name__ == "__main__":
    main()