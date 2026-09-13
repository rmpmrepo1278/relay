#!/usr/bin/env python3
"""personal_brief.py — WS8 Tier 1: context-aware prioritized daily brief.

Morning (07:00) and evening (20:00). Primary path asks the in-container Hermes
agent (native MCP: Google Calendar, Tasks, Gmail) for a prioritized brief;
fallback assembles a local calendar + system-state brief. Sends via
telegram_bridge.send_telegram (which respects the telegram_bridge circuit
breaker, so a broken bridge never spams).

Usage: python3 personal_brief.py morning|evening
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HH = Path.home() / ".hermes"


def run(cmd: str, timeout: int = 170) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def fallback_brief(period: str) -> str:
    """Local fallback: calendar context + system state (no agent call)."""
    try:
        sys.path.insert(0, str(HH / "scripts"))
        import persona_engine as pe
        cal = pe.get_calendar_context() or ""
        state = pe.get_system_state() or {}
        disk = state.get("disk_root", {}).get("pct", "?")
        mem = state.get("mem", {}).get("pct", "?")
        return (
            f"(fallback brief, agent offline)\n{cal}\n"
            f"System: disk {disk}, mem {mem}. See the weekly digest for details."
        )[:3800]
    except Exception as e:
        return f"(fallback brief failed: {e})"


def main() -> int:
    period = sys.argv[1] if len(sys.argv) > 1 else "morning"
    if period == "morning":
        focus = ("Focus: today's meetings (times + anything to prep), deadlines and "
                 "priorities, travel/trip prep, anything needing YOUR action today.")
        emoji = "☀️"
    else:
        focus = ("Focus: what got done today, what to watch tomorrow, anything urgent "
                 "before morning.")
        emoji = "🌙"
    prompt = (
        "You are my proactive personal assistant. Produce a prioritized brief, "
        "max 12 short lines, no preamble, no markdown headers, no em-dashes. "
        "Use ONLY real data from your calendar, tasks and email tools. " + focus
    )
    reply = run(f"docker exec hermes hermes chat --quiet --query {json.dumps(prompt)}")
    text = reply.strip()
    if len(text) < 40:
        text = fallback_brief(period)

    sys.path.insert(0, str(HH / "scripts"))
    from telegram_bridge import send_telegram
    r = send_telegram(f"{emoji} **PA brief**\n{text[:3800]}")
    print("send:", r.get("status"), r.get("reason", ""))
    return 0 if r.get("status") in ("ok", "skipped", "deduped") else 1


if __name__ == "__main__":
    raise SystemExit(main())