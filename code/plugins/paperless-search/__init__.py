import os
import httpx
import re
import json
import logging
import sys
import urllib.request

def _load_env():
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

_load_env()

logger = logging.getLogger(__name__)
PAPERLESS_URL = os.environ.get("PAPERLESS_URL", "http://127.0.0.1:8000")

def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", on_pre_gateway_dispatch)
    print("[paperless-search] plugin loaded", file=sys.stderr, flush=True)

def on_pre_gateway_dispatch(event, **kwargs):
    text = getattr(event, "text", "") or ""
    t = text.strip()
    if not re.search(r"(?i)^/paperless(?:\s|$)", t) and not re.match(r"(?i)paperless(?:\s|$)", t):
        return None

    match = re.search(r"(?i)^/paperless\s+(.*)", t)
    if not match:
        match = re.search(r"(?i)^paperless\s+(.*)", t)
    query = (match.group(1) or "").strip() if match else ""

    if not query:
        _send_telegram("Usage: /paperless <search term>", event)
        return {"action": "skip", "reason": "paperless-search"}

    result = _run_search(query)
    _send_telegram(result, event)
    return {"action": "skip", "reason": "paperless-search"}

def _send_telegram(msg, event):
    try:
        source = getattr(event, "source", None)
        if not source:
            return
        chat_id = getattr(source, "chat_id", "")
        if not chat_id:
            return

        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not bot_token:
            logger.warning("paperless-search: no bot token")
            return

        text = str(msg)[:4000]
        payload = json.dumps({"chat_id": str(chat_id), "text": text}).encode()
        req = urllib.request.Request(
            "https://api.telegram.org/bot" + bot_token + "/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30):
            pass
    except Exception as exc:
        print("[paperless-search] send failed: %s" % exc, file=sys.stderr, flush=True)

def _run_search(query):
    token = os.environ.get("PAPERLESS_API_TOKEN")
    if not token:
        return "Error: PAPERLESS_API_TOKEN not set"
    headers = {"Authorization": "Token " + token}
    try:
        r = httpx.get(PAPERLESS_URL + "/api/documents/?query=" + query + "&limit=5", headers=headers, timeout=10.0)
        r.raise_for_status()
        docs = r.json().get("results", [])
        if not docs:
            return "No documents found for: " + query
        out = ["Found " + str(len(docs)) + ":"]
        for d in docs[:5]:
            title = d.get("title", "Untitled")
            doc_id = d.get("id")
            out.append("  " + str(title) + " (ID: " + str(doc_id) + ")")
        return "\n".join(out)
    except Exception as e:
        return "Error: " + str(e)[:200]
