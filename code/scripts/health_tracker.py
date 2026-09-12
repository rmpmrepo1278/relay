#!/usr/bin/env python3
"""health_tracker.py — Human Health Trend Dashboard.

Tracks personal health signals over time (sleep, energy, mood, exercise) and
renders trend summaries. Data lives in data/health_ts.jsonl (append-only).

CLI / Telegram:
  python3 health_tracker.py log sleep 7.5          # hours last night
  python3 health_tracker.py log energy 3            # 0-5 score
  python3 health_tracker.py log mood 4              # 0-5
  python3 health_tracker.py log exercise 45         # minutes today
  python3 health_tracker.py trend                   # daily average/summary
  python3 health_tracker.py dashboard               # Telegram-rendered view

Returns compact HTML for the listener.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_kits import HERMES_HOME, DATA, append_jsonl, read_json, now_iso

LOG = DATA / "health_ts.jsonl"

FIELDS = ("sleep", "energy", "mood", "exercise")


def _records(days: int = 30) -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for line in LOG.read_text(errors="replace").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        try:
            ts = datetime.fromisoformat(str(r.get("ts", "")).replace("Z", "+00:00"))
        except Exception:
            continue
        if ts >= cutoff:
            out.append(r)
    return out


def log(field: str, value: float) -> dict:
    field = field.strip().lower()
    if field not in FIELDS:
        return {"ok": False, "error": f"unknown field (use {', '.join(FIELDS)})"}
    try:
        value = float(value)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"bad value: {value}"}
    if field in ("energy", "mood") and not (0 <= value <= 5):
        return {"ok": False, "error": f"{field} must be 0-5"}
    if field == "sleep" and not (0 <= value <= 16):
        return {"ok": False, "error": "sleep must be 0-16 hours"}
    if field == "exercise" and not (0 <= value <= 480):
        return {"ok": False, "error": "exercise must be minutes 0-480"}
    rec = {"ts": now_iso(), "field": field, "value": value, "date": datetime.now().strftime("%Y-%m-%d")}
    append_jsonl(LOG, rec)
    return {"ok": True, "logged": rec}


def trend(days: int = 14) -> dict:
    """Daily aggregates + simple trend deltas per field."""
    recs = _records(days)
    by_day = {}
    for r in recs:
        d = r.get("date", r.get("ts", "")[:10])
        by_day.setdefault(d, {}).setdefault(r["field"], []).append(float(r["value"]))
    out = {}
    for f in FIELDS:
        series = []
        for d in sorted(by_day):
            if f in by_day[d]:
                vals = by_day[d][f]
                series.append(round(sum(vals) / len(vals), 1))
        if not series:
            out[f] = {"count": 0}
            continue
        avg = round(sum(series) / len(series), 1)
        recent = sum(series[-7:]) / min(len(series), 7) if series else 0
        prev = sum(series[:-7]) / max(len(series) - 7, 1) if len(series) > 7 else 0
        delta = round(recent - prev, 1) if prev else None
        out[f] = {"count": len(series), "avg": avg, "last": series[-1],
                  "delta_last7": delta, "series": series[-14:]}
    return {"days": days, "fields": out}


def dashboard() -> str:
    t = trend(14)
    lines = ["🏃 <b>Health trends (last 14d)</b>", ""]
    icons = {"sleep": "😴 Sleep (h)", "energy": "⚡ Energy (0-5)",
             "mood": "😊 Mood (0-5)", "exercise": "🏋️ Exercise (min)"}
    any_data = False
    for f in FIELDS:
        d = t["fields"].get(f)
        if not d or not d.get("count"):
            continue
        any_data = True
        arrow = ""
        if d.get("delta_last7") is not None:
            if d["delta_last7"] > 0.2:
                arrow = " ↑"
            elif d["delta_last7"] < -0.2:
                arrow = " ↓"
        lines.append(f"{icons[f]}: <b>{d['last']}</b> (avg {d['avg']}{arrow})")
    if not any_data:
        lines.append("No health data yet.")
    lines.append("")
    lines.append("Log it: <b>/health sleep 7.5</b> · <b>/health energy 3</b> · "
                 "<b>/health mood 4</b> · <b>/health exercise 45</b>")
    return "\n".join(lines)


def status_line() -> str:
    """Short single-line summary for the daily review."""
    t = trend(7)
    parts = []
    for f in ("sleep", "energy"):
        d = t["fields"].get(f)
        if d and d.get("count"):
            parts.append(f"{f}={d['last'] or d['avg']}")
    return " · ".join(parts) if parts else "no data yet"


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_log = sub.add_parser("log"); p_log.add_argument("field"); p_log.add_argument("value")
    sub.add_parser("trend")
    sub.add_parser("dashboard")
    sub.add_parser("nudge")
    args = ap.parse_args(argv)
    if args.cmd == "log":
        r = log(args.field, args.value)
        print(json.dumps(r))
        if not r.get("ok"):
            return 1
        print(dashboard())
        return 0
    if args.cmd == "nudge":
        from agent_kits import send
        ok = send("📊 <b>Weekly health check-in</b>\nReply: <b>/health sleep 7.2</b> · "
                  "<b>/health energy 4</b> · <b>/health mood 4</b> · <b>/health exercise 60</b>")
        return 0 if ok else 1
    if args.cmd == "trend":
        print(json.dumps(trend(14)))
        return 0
    if args.cmd == "dashboard":
        print(dashboard())
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())