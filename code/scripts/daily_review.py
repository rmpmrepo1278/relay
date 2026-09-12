#!/usr/bin/env python3
"""daily_review.py — Nightly Self-Evaluation (closes the learning loop).

Each night it looks back at the day and compiles:
  1. What was intended (intent_tracker) and what actually completed.
  2. Reliability report: scheduler job successes vs failures for today.
  3. A compact day summary from episodic_memory.tsv (today's rows).
  4. Lessons + next-day focus, persisted to memory/ and surfaced to Telegram.

It deliberately does NOT run during the overnight outage window.

CLI:
  python3 daily_review.py            # run the review (nightly, ~21:30)
  python3 daily_review.py --send     # same, but guarantee a Telegram copy
  python3 daily_review.py --days 1   # review the last N days (default 1)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_kits import HERMES_HOME, DATA, STATE, read_json, write_json, append_jsonl, now_iso, send

REVIEW_DIR = DATA / "reviews"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)

_REVIEW_STATE = STATE / "daily_review_state.json"


def _day_bounds(days: int = 1, tz=None) -> tuple[datetime, datetime]:
    tz = tz or timezone.utc
    end = datetime.now(tz)
    start = end - timedelta(days=days)
    return start, end


_META_KEYS = {"last_run", "jobs_run_count", "config_snapshot", "started_at"}


def _job_stats(days: int = 1) -> dict:
    """Aggregate scheduler_state.json (flat: job name -> last run) into counts.
    Each value is {last_status, last_run, elapsed_seconds, returncode, error}."""
    state = read_json(DATA / "scheduler_state.json", {})
    if not isinstance(state, dict):
        return {"total": 0, "ok": 0, "fail": 0, "failed_jobs": []}
    out = {"total": 0, "ok": 0, "fail": 0, "failed_jobs": []}
    start, end = _day_bounds(days)
    for name, rec in state.items():
        if not isinstance(rec, dict) or name in _META_KEYS:
            continue
        st = str(rec.get("last_status") or "").lower()
        if st not in ("success", "failed", "error", "ok", "complete"):
            continue
        ts = rec.get("last_run") or ""
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            continue
        if dt < (end - timedelta(days=days)):
            continue
        out["total"] += 1
        if st in ("success", "ok", "complete"):
            out["ok"] += 1
        else:
            out["fail"] += 1
            out["failed_jobs"].append({"name": name, "ok": 0, "fail": 1})
    out["failed_jobs"].sort(key=lambda x: -x["fail"])
    return out


def _day_events(days: int = 1) -> list[str]:
    """Today's rows from episodic_memory.tsv (col2 = message)."""
    start, _ = _day_bounds(days)
    p = DATA / "episodic_memory.tsv"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        try:
            dt = datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
        except Exception:
            continue
        if dt >= start:
            rows.append(f"{dt.strftime('%H:%M')} {parts[2][:160]}")
    return rows[-25:]


def _intents_today(days: int = 1) -> dict:
    """Split intent_tracker state into completed-today vs still-open."""
    state = read_json(STATE / "intent_state.json", {})
    intents = state.get("intents", [])
    done_t = []
    still_open = []
    start, _ = _day_bounds(days)
    for it in intents:
        done_at = it.get("done_at") or ""
        try:
            dd = datetime.fromisoformat(str(done_at).replace("Z", "+00:00")) if done_at else None
        except Exception:
            dd = None
        if it.get("status") == "done" and dd and dd >= start:
            done_t.append(it)
        elif it.get("status") == "active":
            still_open.append(it)
    return {"done": done_t, "open": still_open[:10]}


def _job_failure_lessons(stats: dict) -> list[str]:
    lessons = []
    for j in stats.get("failed_jobs", [])[:4]:
        lessons.append(f"Job <b>{_e(j['name'])}</b> last run failed — worth investigating.")
    return lessons


def _review_record(days: int = 1, send_msg: bool = True) -> str:
    """Build + persist the review; returns the rendered Telegram text."""
    start, end = _day_bounds(days)
    stats = _job_stats(days)
    events = _day_events(days)
    ints = _intents_today(days)

    lessons = _job_failure_lessons(stats)

    # intent-derived next-day focus: promote open high-priority intents
    import intent_tracker
    intent_tracker.reprioritize()

    # health line (best-effort)
    health_line = ""
    try:
        import health_tracker
        hl = health_tracker.status_line()
        if hl and hl != "no data yet":
            health_line = f"\n🏃 <b>Health:</b> {hl}"
    except Exception:
        pass

    lines = []
    lines.append(f"🌙 <b>Nightly Review — {end:%b %d}</b>")
    lines.append("")
    lines.append(f"🎯 <b>Intents:</b> {len(ints['done'])} completed · "
                 f"{len(ints['open'])} still open")
    if ints["done"]:
        lines.append("   ✓ " + " · ".join(_e(i["title"]) for i in ints["done"]))
    if ints["open"]:
        lines.append("   ◻ " + " · ".join(_e(i["title"]) for i in ints["open"][:5]))
    lines.append("")
    lines.append(f"⚙️ <b>Reliability:</b> {stats['ok']}/{stats['total']} job runs succeeded")
    if stats["failed_jobs"]:
        top = ", ".join(f"{_e(j['name'])}×{j['fail']}" for j in stats["failed_jobs"][:5])
        lines.append(f"   failed: {top}")
    if lessons:
        lines.append("")
        lines.append("🧠 <b>Lessons:</b>")
        lines.extend(f"   - {l}" for l in lessons)
    if events:
        lines.append("")
        lines.append("📆 <b>Day snapshot</b> (latest):")
        lines.extend(f"   · {_e(e)}" for e in events[-6:])
    if health_line:
        lines.append(health_line)
    lines.append("")
    lines.append("➡️ <b>Tomorrow:</b> <b>/priorities</b> · <b>/intent add …</b> to steer the week.")

    text = "\n".join(lines)

    # persist review to disk (plain text for grep-ability) + append to jsonl
    fname = end.strftime("review_%Y-%m-%d.md")
    (REVIEW_DIR / fname).write_text(text)
    append_jsonl(DATA / "daily_review.log.jsonl",
                 {"date": end.strftime("%Y-%m-%d"), "ok": stats["ok"],
                  "fail": stats["fail"], "total": stats["total"]})
    write_json(_REVIEW_STATE, {"last_review": now_iso(), "date": end.strftime("%Y-%m-%d")})

    if send_msg:
        send(text)
    return text


def _e(t: str) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--days", type=int, default=1)
    args = ap.parse_args(argv)

    stat = _job_stats(args.days)
    text = _review_record(args.days, send_msg=args.send)
    if args.send:
        print("sent")
    else:
        print(text)
        print(f"\n[{stat['ok']}/{stat['total']} ok]")
    return 0


if __name__ == "__main__":
    sys.exit(main())