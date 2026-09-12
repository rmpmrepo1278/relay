#!/usr/bin/env python3
"""
trip_planner.py — Trip planning assistant for Chaguli.

Manages trip data, provides itinerary lookups, countdowns, and proactive alerts.
Data synced from the Mac Trip Organizer project.

Usage:
    python3 trip_planner.py status          # Show upcoming trip overview
    python3 trip_planner.py today           # What's happening today (pre-trip prep)
    python3 trip_planner.py itinerary       # Full trip itinerary
    python3 trip_planner.py countdown       # Days until next trip
    python3 trip_planner.py task add <text> # Add a trip task
    python3 trip_planner.py tasks           # Show trip tasks
"""

from __future__ import annotations
import json
import sys
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

HERMES_HOME = Path.home() / ".hermes"
TRIP_DATA_FILE = HERMES_HOME / "data" / "sept-asia-2026.trip.json"
TASKS_FILE = HERMES_HOME / "data" / "trip_tasks.json"


def _load_trip() -> dict:
    if TRIP_DATA_FILE.exists():
        return json.loads(TRIP_DATA_FILE.read_text())
    return {}


def _load_tasks() -> list[dict]:
    if TASKS_FILE.exists():
        return json.loads(TASKS_FILE.read_text())
    return []


def _save_tasks(tasks: list[dict]):
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(json.dumps(tasks, indent=2, default=str))


def cmd_status():
    trip = _load_trip()
    if not trip:
        print("No trip data loaded. Copy a .trip.json file to ~/.hermes/data/")
        return
    today = date.today()
    start = date.fromisoformat(trip["startDate"])
    end = date.fromisoformat(trip["endDate"])
    days_until = (start - today).days
    trip_len = (end - start).days + 1

    lines = [
        f"✈️  <b>{trip['name']}</b>",
        f"   {start} → {end} ({trip_len} days)",
    ]
    if days_until > 0:
        lines.append(f"   ⏰ <b>{days_until} days away</b>")
    elif days_until == 0:
        lines.append(f"   🛫 <b>Departs TODAY!</b>")
    elif days_until < 0:
        if today <= end:
            lines.append(f"   🏝️ <b>You're on this trip!</b> (Day {abs(days_until) + 1})")
        else:
            lines.append(f"   ✅ <b>Trip completed</b> (ended {abs(days_until)} days ago)")

    # Show destinations
    cities = set()
    for day_data in trip.get("locations", {}).values():
        city = day_data.get("city", "").split("→")[0].strip().split(",")[0].strip()
        if city and city != "Travel":
            cities.add(city)
    lines.append(f"   📍 {', '.join(sorted(cities))}")

    # Count events
    events = trip.get("events", [])
    flights = sum(1 for e in events if e.get("type") == "flight")
    hotels = sum(1 for e in events if e.get("type") == "hotel")
    activities = sum(1 for e in events if e.get("type") in ("activity", "restaurant"))
    lines.append(f"   🛩️ {flights} flights · 🏨 {hotels} stays · 🎯 {activities} activities")

    # Next upcoming event
    if days_until <= 7 and days_until >= -1:
        for e in events:
            try:
                e_date = date.fromisoformat(e["date"])
                if e_date >= today:
                    lines.append(f"\n   ➡️ Next up: <b>{e['title']}</b> ({e['time']})")
                    break
            except:
                pass

    tasks = _load_tasks()
    pending = [t for t in tasks if not t.get("done")]
    if pending:
        lines.append(f"\n   📋 {len(pending)} pending tasks")

    print("\n".join(lines))


def cmd_today():
    trip = _load_trip()
    if not trip:
        return
    today = date.today()
    today_str = today.isoformat()
    start = date.fromisoformat(trip["startDate"])
    days_until = (start - today).days

    if days_until > 7:
        print(f"⏰ Trip is {days_until} days away. Nothing urgent today.")
        return

    if days_until > 0:
        print(f"⏰ <b>{days_until} days until {trip['name']}</b>")
        tasks = _load_tasks()
        urgent = [t for t in tasks if not t.get("done")]
        if urgent:
            print(f"\n📋 <b>Trip prep tasks ({len(urgent)} remaining):</b>")
            for t in urgent:
                pri = "🔴" if t.get("priority") == "high" else "🟡" if t.get("priority") == "medium" else "🟢"
                print(f"  {pri} {t['text']}")
        else:
            print("\n✅ All prep tasks done!")
        return

    if today_str in trip.get("locations", {}):
        loc = trip["locations"][today_str]
        print(f"📍 <b>{loc.get('city', 'Today')}</b>")
        if loc.get("note"):
            print(f"   {loc['note']}")

    today_events = [e for e in trip.get("events", []) if e.get("date") == today_str]
    if today_events:
        for e in today_events:
            etype = e.get("type", "?").replace("_", " ")
            print(f"   {e.get('icon', '•')} {e['title']} ({e.get('time', '')[:20]})")
            if e.get("detail"):
                print(f"     {e['detail'][:120]}")


def cmd_itinerary():
    trip = _load_trip()
    if not trip:
        print("No trip data loaded.")
        return

    for day_str in sorted(trip.get("locations", {}).keys()):
        loc = trip["locations"][day_str]
        date_obj = date.fromisoformat(day_str)
        date_label = date_obj.strftime("%a %b %d")
        city = loc.get("city", "?")
        note = loc.get("note", "")
        print(f"\n<b>{date_label}</b> — {city}")
        if note:
            print(f"  {note}")

        day_events = [e for e in trip.get("events", []) if e.get("date") == day_str]
        for e in day_events:
            icon = e.get("icon", "•")
            title = e["title"]
            time_str = e.get("time", "")
            print(f"  {icon} {title} [{time_str}]")


def cmd_countdown():
    trip = _load_trip()
    if not trip:
        return
    today = date.today()
    start = date.fromisoformat(trip["startDate"])
    end = date.fromisoformat(trip["endDate"])
    days_until = (start - today).days
    trip_len = (end - start).days + 1

    if days_until > 0:
        total_prep = 90  # assume ~3 months of planning
        pct = ((total_prep - days_until) / total_prep) * 100
        bar_len = 20
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"📅 <b>{days_until} days until departure</b>")
        print(f"   Prep progress: {bar} {pct:.0f}%")
    elif days_until == 0:
        print("🛫 <b>Trip departs TODAY!</b> Have an amazing trip!")
    elif today <= end:
        day_num = abs(days_until) + 1
        pct = (day_num / trip_len) * 100
        print(f"🏝️ <b>Day {day_num}/{trip_len} of your trip</b> ({pct:.0f}% complete)")
    else:
        print(f"✅ <b>Trip completed</b> ({abs(days_until)} days ago)")


def cmd_task_add(text: str):
    tasks = _load_tasks()
    task = {
        "text": text,
        "done": False,
        "created": datetime.now().isoformat(),
        "priority": "medium",
    }
    tasks.append(task)
    _save_tasks(tasks)
    print(f"✅ Added: {text}")


def cmd_tasks():
    tasks = _load_tasks()
    if not tasks:
        print("No trip tasks yet. Add one with: trip_planner.py task add <text>")
        return
    pending = [t for t in tasks if not t.get("done")]
    done = [t for t in tasks if t.get("done")]
    if pending:
        print(f"📋 <b>Pending ({len(pending)}):</b>")
        for i, t in enumerate(pending, 1):
            pri = "🔴" if t.get("priority") == "high" else "🟡" if t.get("priority") == "medium" else "🟢"
            print(f"  {i}. {pri} {t['text']}")
    if done:
        print(f"\n✅ <b>Completed ({len(done)}):</b>")
        for t in done:
            print(f"  • {t['text']}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    if cmd == "status":
        cmd_status()
    elif cmd == "today":
        cmd_today()
    elif cmd == "itinerary":
        cmd_itinerary()
    elif cmd == "countdown":
        cmd_countdown()
    elif cmd == "task" and len(sys.argv) >= 4 and sys.argv[2] == "add":
        cmd_task_add(" ".join(sys.argv[3:]))
    elif cmd == "tasks":
        cmd_tasks()
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
