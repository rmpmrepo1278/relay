#!/usr/bin/env python3
"""
telegram_bridge.py — Centralized Telegram sender via n8n bridge.

All scripts should use this module instead of:
- hermes CLI (hermes send -t telegram ...)
- Direct Telegram Bot API calls
- Custom send_telegram() functions

Usage:
    from telegram_bridge import send_telegram, send_telegram_html, send_telegram_markdown

    send_telegram("Hello world")
    send_telegram_html("<b>Bold</b> text")
    send_telegram_markdown("*Bold* text")

Environment variables:
    TELEGRAM_BRIDGE_URL - Bridge endpoint (default: http://localhost:9199)
    BRIDGE_AUTH_KEY - Auth key for bridge (default: default-key-change-me)
    TELEGRAM_HOME_CHANNEL - Default chat ID (default: -1003976074764)
    TELEGRAM_HOME_THREAD - Default thread ID (optional)
"""

from __future__ import annotations
import json
import os
import re
import urllib.request
from typing import Optional


# ─── Configuration ────────────────────────────────────────────────────────────

BRIDGE_URL = os.environ.get("TELEGRAM_BRIDGE_URL", "http://localhost:9199")
BRIDGE_AUTH = os.environ.get("BRIDGE_AUTH_KEY", "default-key-change-me")
DEFAULT_CHAT_ID = os.environ.get("TELEGRAM_HOME_CHANNEL", "-1003976074764")
DEFAULT_THREAD_ID = os.environ.get("TELEGRAM_HOME_THREAD")


# ─── Internal ────────────────────────────────────────────────────────────────

def _post(endpoint: str, data: dict, timeout: int = 10) -> dict:
    """POST to bridge endpoint with auth."""
    url = f"{BRIDGE_URL}{endpoint}"
    body = json.dumps(data).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BRIDGE_AUTH}",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── Public API ───────────────────────────────────────────────────────────────

# Patterns that indicate a fabricated/stub shell/docker output that must never be
# treated as verified success (e.g. the agent inventing an install_manager.py
# run + fake "docker ps" row with placeholder IDs).
_STUB_PATTERNS = [
    re.compile(r"sha256:abcd000000000000", re.I),           # placeholder image digest
    re.compile(r"1234567890ab", re.I),                       # 40-hex placeholder container ID
    re.compile(r"\bexample-component\b", re.I),              # the synthetic install demo
    re.compile(r"image:\s*example/component", re.I),         # the fabricated image ref
    re.compile(r"example\.component:1\.4\.2", re.I),         # stub version
]


def _verify_message(text: str) -> str:
    """
    Guard against fabricated shell/docker output being relayed as fact.

    Detects placeholder container IDs, fake image digests, and bogus scripts,
    then prefixes the message and reroutes to the infrastructure thread so a
    human can verify before any "installed"/"healthy" claim is trusted.
    """
    flagged = [p.pattern for p in _STUB_PATTERNS if p.search(text)]
    if flagged:
        warning = (
            "⚠️ UNVERIFIED — agent may have fabricated output. Stubs detected: "
            + ", ".join(flagged)
            + ". Verify the claimed container/install before trusting:\n"
            "```\ndocker ps -a | grep example\npython3 ~/.hermes/scripts/assess_idea.py --check\n```\n\n"
        )
        return warning + text
    return text


def send_telegram(
    text: str,
    chat_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    parse_mode: str = "HTML",
    timeout: int = 10,
    priority: str = "normal",
    category: Optional[str] = None,
    dedup_window: Optional[float] = None,
) -> dict:
    """
    Send a message to Telegram via the bridge.

    Args:
        text: Message text
        chat_id: Target chat ID (default: TELEGRAM_HOME_CHANNEL)
        thread_id: Target thread ID (default: TELEGRAM_HOME_THREAD)
        parse_mode: "HTML", "Markdown", or "" for no parsing
        timeout: Request timeout in seconds
        priority: "normal" or "critical" (critical bypasses throttling)
        category: Override auto-detected category (e.g. "email_intelligence")
        dedup_window: Exact-duplicate suppression window in seconds (default 120)

    Returns:
        Dict with status and response/error details
    """
    text = _verify_message(text)
    payload = {
        "text": text,
        "chat_id": chat_id or DEFAULT_CHAT_ID,
        "parse_mode": parse_mode,
        "priority": priority,
    }
    if thread_id or DEFAULT_THREAD_ID:
        payload["message_thread_id"] = thread_id or DEFAULT_THREAD_ID
    if category:
        payload["category"] = category
    if dedup_window is not None:
        payload["dedup_window"] = dedup_window

    return _post("/telegram-send", payload, timeout)


def send_telegram_html(
    text: str,
    chat_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    timeout: int = 10,
) -> dict:
    """Send HTML-formatted message."""
    return send_telegram(text, chat_id, thread_id, parse_mode="HTML", timeout=timeout)


def send_telegram_markdown(
    text: str,
    chat_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    timeout: int = 10,
) -> dict:
    """Send Markdown-formatted message."""
    return send_telegram(text, chat_id, thread_id, parse_mode="Markdown", timeout=timeout)


# ─── Convenience: Topic-based routing ────────────────────────────────────────

TOPIC_CHAT_IDS = {
    "general": "-1003976074764",      # General
    "infrastructure": "-1003976074764",  # Infrastructure (topic 2)
    "career": "-1003976074764",        # Career-Ops (topic 3)
    "knowledge": "-1003976074764",     # Knowledge-Base (topic 4)
}

TOPIC_THREAD_IDS = {
    "general": None,
    "infrastructure": "2",
    "career": "3",
    "knowledge": "4",
}


# ─── Backwards compatibility ──────────────────────────────────────────────────

def send(message: str, target: str = "telegram") -> dict:
    """
    Backwards-compatible function matching hermes CLI signature.

    Usage: send("message", "telegram")
    """
    if target == "telegram":
        return send_telegram(message)
    return {"status": "error", "message": f"Unknown target: {target}"}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        msg = " ".join(sys.argv[1:])
        result = send_telegram(msg)
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python3 telegram_bridge.py <message>")