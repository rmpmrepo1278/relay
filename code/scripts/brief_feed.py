#!/usr/bin/env python3
"""brief_feed.py — the daily "Muse app feed": one Telegram digest of your day.

Aggregates what the stack already produces into a single morning brief:
  * commitments due today / overdue
  * upcoming calendar events (next 24h)
  * capsule outcome summary (how autonomous actions landed)
  * career-ops status (from career state)
  * system health signals
  * one proactive "idea" line (interest model / latest research digest)

Everything degrades gracefully if a source is missing.

CLI:
  python3 brief_feed.py --render     # render the brief text (used by /brief)
  python3 brief_feed.py --send       # render + send (scheduler job, 07:30)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from agent_kits import HERMES_HOME, DATA, STATE, read_json, send, now_iso

MEMORY_DIR = HERMES_HOME / "collaborator-memory" / "memory"


def _commitments_brief() -> str:
    from agent_kits import load_commitments
    c = load_commitments()
    open_c = [x for x in c if x.get("status") == "open"]
    today = now_iso()[:10]
    due_today = [x for x in open_c if (x.get("due") or "")[:10] == today]
    overdue = [x for x in open_c if (x.get("due") or "")[:10] < today]
    out = []
    if due_today:
        out.append("⏰ Due today: " + ", ".join(_txt(x) for x in due_today[:3]))
    if overdue:
        out.append("🔥 Overdue: " + ", ".join(_txt(x) for x in overdue[:3]))
    if open_c and not out:
        out.append(f"📥 {len(open_c)} open commitments (none urgent).")
    return "\n".join(out[:4]) or "📥 No outstanding commitments."


def _txt(x: dict) -> str:
    return (x.get("text") or x.get("commitment") or x.get("title") or str(x))[:60]


def _calendar_brief() -> str:
    ev = read_json(STATE / "calendar_events.json", {})
    events = ev.get("events") or ev.get("items") or []
    now = datetime.now(timezone.utc)
    up = []
    for e in events[:20]:
        s = (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date") or ""
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            continue
        if now <= dt <= now + timedelta(hours=24):
            up.append((dt, e.get("summary", "(no title)")))
    if not up:
        return "🗓️ No events in the next 24h."
    return "🗓️ Up next:\n" + "\n".join(
        f"• {dt.strftime('%H:%M')} {t}" for dt, t in sorted(up)[:5])


def _capsules_brief() -> str:
    n = 0
    hits = []
    for p in DATA.glob("capsules*.json*"):
        try:
            d = read_json(p, [])
            if isinstance(d, dict):
                d = list(d.values())
            ok = [x for x in d if (x.get("outcome") or x.get("result") or "").lower() in ("success", "ok")]
            n += len(ok)
        except Exception:
            continue
    return f"📦 {n} capsule action(s) landed successfully." if n else "📦 No capsule outcomes today."


def _career_brief() -> str:
    tries = [DATA / "career_state.json", DATA / "career_briefing.json",
             HERMES_HOME / "career-ops" / "state.json"]
    for p in tries:
        d = read_json(p, {})
        if d:
            return f"💼 Career-ops: {str(d)[:80]}"
    return "💼 No career-ops state file."


def _health_brief() -> str:
    h = read_json(DATA / "health_signals.json", {})
    if not h:
        return "🩺 No health signals file."
    keys = list(h.keys())
    return f"🩺 Health: {len(keys)} signal(s): {', '.join(keys[:5])}"


def _idea_brief() -> str:
    for p in (STATE / "interest_model.json", DATA / "interests.json",
              HERMES_HOME / "research" / "latest.json"):
        d = read_json(p, {})
        if d:
            try:
                sample = d if isinstance(d, list) else (list(d.values())[0] if isinstance(d, dict) else d)
                return f"💡 Idea: {str(sample)[:120]}"
            except Exception:
                continue
    return "💡 No idea feed yet."


def render() -> dict:
    sections = [
        (_commitments_brief(), "commitments"),
        (_calendar_brief(), "calendar"),
        (_capsules_brief(), "capsules"),
        (_career_brief(), "career"),
        (_health_brief(), "health"),
    ]
    text = "\n\n".join(t for t, _ in sections)
    return {"brief": f"{text}" }


def send_brief(chat_id=None) -> dict:
    b = render()
    ok = send(b["brief"], chat_id=chat_id)
    return {"ok": ok, "sent": now_iso(), "brief_len": len(b["brief"])}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--send", action="store_true")
    args = ap.parse_args(argv)
    if args.send:
        print(send_brief())
    else:
        print(render()["brief"])
    return 0


if __name__ == "__main__":
    sys.exit(main())