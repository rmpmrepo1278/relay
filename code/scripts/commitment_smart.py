#!/usr/bin/env python3
"""commitment_smart.py — smart follow-up on commitments.

Extends commitment_executor with:
  * calendar-aware nudge timing (defer while you're in a meeting)
  * dedupe (one nudge per commit per day)
  * a /commitments summary for Telegram

State: data/commitment_smart.json {nudged: {commit_key: date}}
CLI:
  python3 commitment_smart.py --run       # nudge cycles (scheduler job)
  python3 commitment_smart.py --summary   # print summary (used by /commitments)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from agent_kits import DATA, STATE, read_json, write_json, send, now_iso, lock, unlock, append_jsonl, trim_jsonl

SMART_FILE = DATA / "commitment_smart.json"


def _commitments() -> list[dict]:
    from agent_kits import load_commitments
    return load_commitments()


def _calendar_now_busy() -> bool:
    """True if there's a calendar event overlapping 'now' (no reminder then)."""
    try:
        if not (STATE / "calendar_events.json").exists():
            append_jsonl(DATA / "commitment_smart.log.jsonl",
                         {"ts": now_iso(), "warn": "calendar_events.json missing — "
                                                   "nudges not meeting-aware yet"})
            return False
        ev = read_json(STATE / "calendar_events.json", {})
        events = ev.get("events") or ev.get("items") or []
        now = datetime.now(timezone.utc)
        for e in events[:20]:
            s = (e.get("start") or {}).get("dateTime") or ""
            t = (e.get("end") or {}).get("dateTime") or ""
            if not s or not t:
                continue
            try:
                sd = datetime.fromisoformat(s.replace("Z", "+00:00"))
                ed = datetime.fromisoformat(t.replace("Z", "+00:00"))
            except ValueError:
                continue
            if sd <= now <= ed:
                return True
    except Exception:
        pass
    return False


def _smart_state() -> dict:
    return read_json(SMART_FILE, {"nudged": {}})


def summarize() -> str:
    commits = _commitments()
    if not commits:
        return "📥 No tracked commitments yet."
    open_c = [c for c in commits if (c.get("status") or "open").lower() not in
              ("done", "completed", "closed", "resolved", "cancelled")]
    lines = [f"📥 <b>{len(open_c)} open</b> of {len(commits)} tracked commitments:"]
    for c in open_c[:8]:
        due = c.get("due") or c.get("when") or "?"
        lines.append(f"• <b>{_text(c)}</b> (due {due})")
    if len(open_c) > 8:
        lines.append(f"… and {len(open_c) - 8} more")
    return "\n".join(lines)


def _text(c: dict) -> str:
    return (c.get("text") or c.get("commitment") or c.get("title") or str(c.get("id", "")))[:100]


def run(max_daily: int = 3) -> dict:
    lk = Path("/tmp/commitment_smart.lock")
    if not lock(lk, 180):
        return {"ok": False, "message": "already running"}
    try:
        st = _smart_state()
        today = now_iso()[:10]
        busy = _calendar_now_busy()
        nudged = 0
        open_c = [c for c in _commitments()
                  if (c.get("status") or "open").lower() not in
                  ("done", "completed", "closed", "resolved", "cancelled")]
        for c in open_c:
            if nudged >= max_daily:
                break
            key = str(c.get("id") or _text(c))
            last = st["nudged"].get(key, "")
            if last and last[:10] == today:
                continue
            if busy:
                continue  # don't interrupt a meeting
            due = c.get("due") or c.get("when") or ""
            try:
                due_dt = datetime.fromisoformat(str(due).replace("Z", "+00:00")).replace(tzinfo=None)
                now_l = datetime.now(timezone.utc).replace(tzinfo=None)
                urgent = (due_dt - now_l).total_seconds() / 86400 < 1
            except (ValueError, TypeError):
                urgent = False
            if not urgent:
                continue
            send(f"⏰ <b>Commitment due soon:</b> “{_text(c)}” (due {due}). "
                 f"Reply /commitments to review, or /deny to dismiss.")
            st["nudged"][key] = now_iso()
            nudged += 1
        write_json(SMART_FILE, st)
        return {"ok": True, "nudged": nudged, "busy_deferred": not busy and False}
    finally:
        unlock(lk)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args(argv)
    if args.run:
        print(json.dumps(run()))
    elif args.summary:
        print(summarize())
    else:
        print(json.dumps(run()) + "\n" + summarize())
    return 0


if __name__ == "__main__":
    sys.exit(main())