import os
import httpx
import re
import json
import urllib.request
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

PAPERLESS_URL = os.environ.get("PAPERLESS_URL", "http://127.0.0.1:8000")
PAPERLESS_PATTERN = re.compile(r"^/paperless(?:_search)?\s*(.*)", re.IGNORECASE)

def handle(event_type: str, **kwargs) -> Any:
    if event_type != "pre_gateway_dispatch":
        return None
    
    event = kwargs.get("event")
    if not event:
        logger.warning("paperless-search: no event in kwargs")
        return None
    
    text = getattr(event, "text", "") or ""
    logger.info(f"paperless-search hook called: text={text[:50]}")
    
    match = PAPERLESS_PATTERN.match(text.strip())
    if not match:
        logger.info(f"paperless-search: no regex match for {text[:30]}")
        return None
    
    query = match.group(1).strip()
    if not query:
        return {"action": "skip", "text": "Usage: /paperless <search term>"}
    
    logger.info(f"paperless-search: processing query={query}")
    result = run_paperless_search(query)
    if result:
        _send_response(result, event)
        return {"action": "skip", "reason": "paperless-search"}
    return None

def _send_response(response_text: str, event):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    source = getattr(event, "source", None)
    if not source or not bot_token:
        logger.warning(f"paperless-search: no source or bot_token, source={source}")
        return
    chat_id = getattr(source, "chat_id", "") or ""
    msg_text = f"📄 {response_text}"[:4000]
    payload = json.dumps({"chat_id": chat_id, "text": msg_text, "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=payload, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=30)

def run_paperless_search(query):
    token = os.getenv("PAPERLESS_API_TOKEN")
    if not token:
        return "Error: PAPERLESS_API_TOKEN not set"
    headers = {"Authorization": f"Token {token}"}
    try:
        r = httpx.get(f"{PAPERLESS_URL}/api/documents/?query={query}&limit=5", headers=headers, timeout=10.0)
        r.raise_for_status()
        docs = r.json().get("results", [])
        if not docs:
            return "No documents found"
        out = [f"Found {len(docs)}:"]
        for d in docs[:5]:
            title = d.get("title", "Untitled")
            doc_id = d.get("id")
            out.append(f"  {title} (ID: {doc_id})")
        return "\n".join(out)
    except Exception as e:
        return f"Error: {e}"
