"""telegram-notify hook — Telegram notifications for bridge /run and agent turns.

Fires on:
  - command:run / command:hrun  → announce long-running shell commands to the
    Telegram channel so the user knows a bridge /run is executing.
  - agent:end                   → record a short completion summary to the local
    log ONLY (never posted to Telegram). Per-turn "Agent turn done" blobs used
    to be echoed into the same Telegram chat the gateway transcribes, so the
    agent's own notifications fed straight back into the conversation context,
    bloated it past the compression threshold, and triggered repeated 413 /
    session auto-resets.

Uses the n8n host bridge /telegram-send endpoint (outbound-only, no callbacks),
so it never blocks the gateway pipeline.
"""
import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

BRIDGE_URL = os.environ.get("TELEGRAM_BRIDGE_URL", "http://127.0.0.1:9199")
BRIDGE_AUTH = os.environ.get("BRIDGE_AUTH_KEY", "default-key-change-me")
CHAT_ID = os.environ.get("TELEGRAM_HOME_CHANNEL", "-1003976074764")
NOTIFY_MIN_RUN_LEN = 30
NOTIFY_MIN_RESPONSE_LEN = 400
_SELF_MARKERS = ("✅ Agent turn done", "⚙️ Bridge /")
LOG_DIR = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "logs"
TURN_LOG = LOG_DIR / "telegram_notify.log"


def _send_telegram(text: str) -> None:
    payload = json.dumps({"text": text[:3800], "chat_id": CHAT_ID}).encode()
    req = urllib.request.Request(
        f"{BRIDGE_URL}/telegram-send",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {BRIDGE_AUTH}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as _:
            pass
    except Exception as e:
        logger.warning("telegram-notify send failed: %s", e)


def _handle_command(ctx: dict) -> None:
    args = (ctx.get("raw_args") or "").strip()
    cmd = ctx.get("command", "")
    if not args:
        return
    if len(args) < NOTIFY_MIN_RUN_LEN:
        return
    platform = ctx.get("platform", "")
    user = ctx.get("user_id", "")
    _send_telegram(
        f"⚙️ Bridge /{cmd} executing on {platform} (user {user}):\n`{args[:200]}`"
    )


def _log_turn(ctx: dict, snippet: str) -> None:
    """Record a finished turn to the local log (never posted to Telegram)."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(TURN_LOG, "a") as f:
            f.write(
                f"[{datetime.now(timezone.utc).isoformat()}] "
                f"agent:end platform={ctx.get('platform', '')} "
                f"snippet={snippet!r}\n"
            )
    except Exception:
        pass


def _handle_agent_end(ctx: dict) -> None:
    response = (ctx.get("response") or "").strip()
    if not response:
        return
    # Skip turns triggered by our own notifications (feedback-loop guard).
    message = ctx.get("message") or ""
    if any(m in message for m in _SELF_MARKERS):
        return
    # Only record substantial output to avoid noise on terse replies.
    if len(response) < NOTIFY_MIN_RESPONSE_LEN:
        return
    snippet = response[:300].replace("\n", " ")
    _log_turn(ctx, snippet)


def handle(event_type: str, context: dict = None) -> None:
    ctx = context or {}
    if event_type in ("command:run", "command:hrun"):
        _handle_command(ctx)
    elif event_type == "agent:end":
        _handle_agent_end(ctx)
