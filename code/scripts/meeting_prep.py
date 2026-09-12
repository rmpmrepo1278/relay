#!/usr/bin/env python3
"""meeting_prep.py — 10-minute-before meeting briefing, dropped to Telegram.

Uses the existing calendar cache (calendar_intelligence writes
state/calendar_events.json) and pulls relevant context from the memory topics
+ capsules (the "Rahi" meeting-prep card pattern).

Cleans up reminders with DATA/meeting_preps.json so you get each meeting once.

CLI:
  python3 meeting_prep.py --run          # send prep for next meetings (scheduler job)
  python3 meeting_prep.py --next         # print the next meeting
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from agent_kits import HERMES_HOME, DATA, STATE, read_json, write_json, send, sanitize_name, now_iso, append_jsonl, trim_jsonl

CACHE_FILE = STATE / "calendar_events.json"
PREPS_FILE = DATA / "meeting_preps.json"


def _events() -> list[dict]:
    data = read_json(CACHE_FILE, {"events": [], "items": []})
    if isinstance(data, list):
        return data
    return data.get("events") or data.get("items") or []


def _context_matches(needle: str, limit: int = 3) -> list[str]:
    """Best-effort context extraction from memory topics for an attendee/title."""
    hits = []
    needle = needle.lower()
    for base in (HERMES_HOME / "collaborator-memory" / "memory", HERMES_HOME / "memory_topics"):
        if not base.exists():
            continue
        for p in base.glob("*.md"):
            if p.stem == "MEMORY":
                continue
            try:
                for ln in p.read_text(errors="replace").splitlines():
                    if needle in ln.lower():
                        hits.append(f"{p.stem}: {ln.strip()[:140]}")
            except OSError:
                continue
    return hits[:limit]


def upcoming(mins: int = 15) -> list[dict]:
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(minutes=mins)
    out = []
    for e in _events():
        start = e.get("start", {})
        dt_str = start.get("dateTime") or start.get("date") or ""
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        if now <= dt <= horizon:
            out.append({
                "id": str(e.get("id", "")),
                "summary": e.get("summary", "(no title)"),
                "when": dt.isoformat(),
                "attendees": [a.get("email", "").split("@")[0]
                              for a in e.get("attendees", []) if a.get("email")][:6],
            })
    return out


def prep_card(meeting: dict) -> str:
    title = meeting.get("summary", "")
    when = meeting.get("when", "")
    people = ", ".join(meeting.get("attendees", []))
    ctx = []
    for p in meeting.get("attendees", []):
        ctx += _context_matches(p, limit=1)
    ctx += _context_matches(re.sub(r"\W+", " ", title)[:40], limit=2)
    ctx = [c for c in ctx if c not in ctx[:ctx.index(c)]][:4] if ctx else []
    lines = [
        "🗓️ <b>Meeting in a few minutes</b>",
        f"<b>{title}</b>",
        f"🕐 {when}",
    ]
    if people:
        lines.append(f"👥 {people}")
    if ctx:
        lines.append("\n📎 From memory:\n" + "\n".join("• " + c for c in ctx))
    else:
        lines.append("\n📎 (no memory context yet — add notes with /remember)")
    return "\n".join(lines)


def past_meetings(mins: int = 90) -> list[dict]:
    """Meetings that ended within the last `mins` (for post-meeting capture)."""
    now = datetime.now(timezone.utc)
    out = []
    for e in _events():
        start = e.get("start", {})
        end = e.get("end", {})
        dt_str = start.get("dateTime") or start.get("date") or ""
        end_str = end.get("dateTime") or end.get("date") or ""
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00")) if end_str else dt + timedelta(minutes=30)
        except ValueError:
            continue
        if end_dt <= now and now - end_dt <= timedelta(minutes=mins):
            out.append({
                "id": str(e.get("id", "")),
                "summary": e.get("summary", "(no title)"),
                "when": end_dt.isoformat(),
                "attendees": [a.get("email", "").split("@")[0]
                              for a in e.get("attendees", []) if a.get("email")][:6],
            })
    return out


def conflict_scan() -> list[dict]:
    """Detect overlapping events on the current day window."""
    now = datetime.now(timezone.utc)
    day_start = now - timedelta(hours=2)
    day_end = now + timedelta(hours=14)
    parsed = []
    for e in _events():
        start = e.get("start", {})
        end = e.get("end", {})
        s = start.get("dateTime") or start.get("date") or ""
        en = end.get("dateTime") or ""
        try:
            sdt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            continue
        if not (day_start <= sdt <= day_end):
            continue
        edt = datetime.fromisoformat(en.replace("Z", "+00:00")) if en else sdt + timedelta(minutes=30)
        parsed.append({"id": str(e.get("id", "")), "summary": e.get("summary", "(no title)"),
                       "start": sdt, "end": edt})
    parsed.sort(key=lambda x: x["start"])
    conflicts = []
    for i in range(len(parsed) - 1):
        a, b = parsed[i], parsed[i + 1]
        if a["end"] > b["start"]:
            conflicts.append({
                "a": f"{a['summary']} ({a['start'].strftime('%H:%M')}-{a['end'].strftime('%H:%M')})",
                "b": f"{b['summary']} ({b['start'].strftime('%H:%M')}-{b['end'].strftime('%H:%M')})",
            })
    return conflicts


def energy_note() -> str:
    """Best-effort energy hint from wellness_state.json if it's recent."""
    ws = read_json(DATA / "wellness_state.json", {})
    try:
        checked = datetime.fromisoformat(str(ws.get("checked_at", "")).replace("Z", "+00:00"))
    except Exception:
        return ""
    if (datetime.now(timezone.utc) - checked).days > 3:
        return ""
    level = ws.get("level", "")
    if level in ("stressed", "low"):
        return "\n🔋 Energy check: low-today — keep meetings light."
    if level == "stressed":
        return "\n🔋 Energy check: stressed window — push prep-heavy meetings."
    return ""


def after_capture() -> dict:
    """Nudge to capture action items after a finished meeting (once each)."""
    state = read_json(DATA / "post_meeting_capture.json", {"sent": {}})
    sent = state.get("sent", {})
    done, skipped = [], []
    for m in past_meetings():
        key = str(m["id"]) or m["when"]
        if key in sent and sent[key]:
            skipped.append(key)
            continue
        title = m.get("summary", "")
        lines = [
            "✅ <b>Meeting finished</b>",
            f"<b>{title}</b>",
            f"💭 Capture action items so they land in memory: "
            f"<b>/remember meeting-{sanitize_name(title)[:24] or 'notes'} …</b>"
            f" · or <b>/intent add follow-up on {title} [--priority medium]</b>",
            "Or reply <b>/ignore</b> to skip this one.",
        ]
        if energy_note():
            lines.append(energy_note())
        ok = send("\n".join(lines))
        if ok:
            sent[key] = now_iso()
            done.append(title)
    write_json(DATA / "post_meeting_capture.json", {"sent": sent})
    return {"ok": True, "captured": done, "skipped": len(skipped)}


def run() -> dict:
    if not CACHE_FILE.exists():
        append_jsonl(DATA / "meeting_prep.log.jsonl",
                     {"ts": now_iso(), "warn": "calendar_events.json missing — "
                                               "calendar_intelligence not feeding it yet, no prep cards sent"})
        return {"ok": True, "sent": [], "info": "calendar cache missing — waiting for calendar source"}
    preps = read_json(PREPS_FILE, {"sent": {}})
    sent = preps["sent"]
    done, skipped = [], []
    for m in upcoming():
        key = str(m["id"]) or m["when"]
        if key in sent and sent[key]:
            skipped.append(key)
            continue
        ok = send(prep_card(m))
        if ok:
            sent[key] = now_iso()
            done.append(m.get("summary", key))
    write_json(PREPS_FILE, {"sent": sent})
    return {"ok": True, "sent": done, "skipped": len(skipped)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--next", action="store_true")
    ap.add_argument("--after", action="store_true")
    ap.add_argument("--conflicts", action="store_true")
    args = ap.parse_args(argv)
    if args.after:
        r = after_capture()
        print(json.dumps(r))
    elif args.conflicts:
        print(json.dumps(conflict_scan(), default=str))
    elif args.next:
        for m in upcoming(240):
            print(json.dumps(m, default=str))
    else:
        print(json.dumps(run()))
    return 0


if __name__ == "__main__":
    sys.exit(main())