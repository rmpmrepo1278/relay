#!/usr/bin/env python3
"""preempt_triggers.py — WS8 Tier 2: preemption triggers (trip checklists, due/bill alerts).

Runs ~every 20 min. Sources: the existing calendar cache
(state/calendar_events.json, same as meeting_prep) + calendar_intelligence brief
fallback. Sends ONE telegram per trigger/event/day via telegram_bridge (circuit
breaker aware) and dedups with data/preempt_sent.json.

Triggers implemented:
  trip     — calendar events in the next 36h titled trip/travel/flight/train/etc.
             -> travel checklist (documents, bookings, check-in, connections).
  due      — calendar events in the next 26h titled due/bill/renewal/payment/tax
             -> payment/due alert (T-24h and T-3h windows, dedup per window).
  weather  — optional: once per morning if PREEMPT_WEATHER_LAT/LON env set
             (Open-Meteo, no key). Traffic: no free data source (would need a
             Google Maps API key) -> documented, not implemented.

Usage: python3 preempt_triggers.py --run   (scheduler job "preempt_triggers")
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HH = Path.home() / ".hermes"
STATE = HH / "state"
DATA = HH / "data"
CACHE_FILE = STATE / "calendar_events.json"
SENT_FILE = DATA / "preempt_sent.json"

TRIP_RE = re.compile(r"\b(trip|travel|flight|train|depart|fly|vacation|holiday|itinerary)\b", re.I)
DUE_RE = re.compile(r"\b(due|bill|payment|renewal|tax|invoice|pay)\b", re.I)
CHECKLIST = [
    "Docs: passport / visa / IDs (check expiry)",
    "Bookings confirmed: hotels, flights/trains, transfers",
    "Check-in window + seat selection (if not done)",
    "Cash/cards + travel insurance + roaming or eSIM plan",
    "Chargers, adapters, meds; share itinerary with family",
]


def now() -> datetime:
    return datetime.now(timezone.utc)


def read_json(p: Path, dft):
    try:
        return json.loads(p.read_text())
    except Exception:
        return dft


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, default=str))


def events() -> list[dict]:
    data = read_json(CACHE_FILE, {"events": [], "items": []})
    if isinstance(data, list):
        return data
    return data.get("events") or data.get("items") or []


def send(text: str) -> dict:
    sys.path.insert(0, str(HH / "scripts"))
    from telegram_bridge import send_telegram
    return send_telegram(text)


def _dttm(e: dict):
    """Best-effort event start as UTC datetime."""
    for key in ("start", "when", "dateTime"):
        v = e.get(key)
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
            except Exception:
                continue
    return None


def trigger_trip(events: list, sent: dict):
    horizon = now() + timedelta(hours=36)
    for e in events:
        title = str(e.get("title") or e.get("summary") or e.get("name") or "")
        if not TRIP_RE.search(title):
            continue
        start = _dttm(e)
        if start is None or not (now() < start <= horizon):
            continue
        eid = str(e.get("id") or title)
        day = start.date().isoformat()
        if sent.get("trip", {}).get(eid) == day:
            continue
        sent.setdefault("trip", {})[eid] = day
        delta = start - now()
        when = f"{int(delta.total_seconds() // 3600)}h from now" if delta.total_seconds() < 24 * 3600 else "tomorrow"
        return (f"Trip preempt: {title} starts {when}.\n" + "\n".join(f"- {c}" for c in CHECKLIST))
    return None


def trigger_due(events: list, sent: dict):
    nowt = now()
    for window, horiz in (("d1", timedelta(hours=26)), ("h3", timedelta(hours=3))):
        lim = nowt + horiz
        for e in events:
            title = str(e.get("title") or e.get("summary") or e.get("name") or "")
            if not DUE_RE.search(title):
                continue
            start = _dttm(e)
            if start is None or not (nowt < start <= lim):
                continue
            eid = str(e.get("id") or title)
            key = f"{eid}:{window}"
            if sent.get("due", {}).get(key):
                continue
            sent.setdefault("due", {})[key] = nowt.isoformat()
            tag = "24h" if window == "d1" else "3h"
            return (f"Due in ~{tag}: {title} (at {start.strftime('%a %H:%M')} UTC). "
                    f"Add to today's short list if not done.")
    return None


def trigger_weather():
    lat = os.environ.get("PREEMPT_WEATHER_LAT")
    lon = os.environ.get("PREEMPT_WEATHER_LON")
    if not lat or not lon:
        return None
    today = now().date().isoformat()
    if read_json(SENT_FILE, {}).get("weather") == today:
        return None
    try:
        r = subprocess.run(
            ["curl", "-fsS", "--max-time", "12",
             "https://api.open-meteo.com/v1/forecast",
             "--get", "--data-urlencode", f"latitude={lat}",
             "--data-urlencode", f"longitude={lon}",
             "--data-urlencode", "daily=temperature_2m_max,temperature_2m_min,precipitation_sum",
             "--data-urlencode", "timezone=auto"],
            capture_output=True, text=True, timeout=20)
        j = json.loads(r.stdout)
        d = j["daily"]
        i = 0
        out = (f"Weather today: {d['temperature_2m_max'][i]} / {d['temperature_2m_min'][i]} C, "
               f"precip {d['precipitation_sum'][i]}mm. (Open-Meteo, ~{j.get('timezone')})")
        return out
    except Exception:
        return None  # silent: optional trigger, don't spam on failure


def main() -> int:
    sent = read_json(SENT_FILE, {})
    evs = events()
    if not evs:
        try:
            r = subprocess.run([sys.executable, str(HH / "scripts" / "calendar_intelligence.py"), "--brief"],
                               capture_output=True, text=True, timeout=20)
            if r.stdout.strip():
                evs = [{"title": r.stdout.strip()[:300], "start": now().isoformat()}]
        except Exception:
            evs = []
    msgs = []
    for fn in (lambda: trigger_trip(evs, sent), lambda: trigger_due(evs, sent), trigger_weather):
        try:
            m = fn()
            if m:
                msgs.append(m)
        except Exception:
            continue
    if msgs:
        write_json(SENT_FILE, sent)
        r = send("\n\n".join(msgs)[:3800])
        print("send:", r.get("status"), r.get("reason", ""))
        return 0 if r.get("status") in ("ok", "skipped", "deduped") else 1
    write_json(SENT_FILE, sent)
    print("preempt: nothing due")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())