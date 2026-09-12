#!/usr/bin/env python3
# habit-gamification check.py — Check in a habit and update streaks/rewards
# ponytail: minimal, read habits.json, update in place, no deps

import sys, json
from pathlib import Path
from datetime import datetime, date

HABITS_FILE = Path.home() / ".hermes/habits/habits.json"
POINTS_FILE = Path.home() / ".hermes/habits/points.json"
BADGES = {"7": "🔥", "30": "🔥🔥", "100": "💎"}

def check(habit_id: str, notes: str = ""):
    habits = json.loads(HABITS_FILE.read_text())
    today = date.today().isoformat()

    for h in habits.get("habits", []):
        if h.get("id") == habit_id:
            history = h.get("history", {})
            yesterday = (date.today() - __import__('datetime').timedelta(days=1)).isoformat()

            streak = h.get("streak_current", 0)
            if yesterday in history and history.get(yesterday, {}).get("done"):
                streak += 1
            else:
                streak = 1  # Start new streak

            longest = max(h.get("streak_longest", 0), streak)

            # Record today
            history[today] = {"done": True, "value": h.get("target_per_week", 1), "notes": notes}
            h["history"] = history
            h["streak_current"] = streak
            h["streak_longest"] = longest

            # Process achievements
            badges = []
            pts = 1  # Base point
            for threshold, badge in BADGES.items():
                if streak == int(threshold):
                    badges.append(badge)
                    pts += {"7": 5, "30": 15, "100": 50}[threshold]

            if badges:
                h["current_badge"] = badges[-1]  # Top badge

            HABITS_FILE.write_text(json.dumps(habits, indent=2))

            # Update points
            points = json.loads(POINTS_FILE.read_text()) if POINTS_FILE.exists() else {"total": 0, "achievements": []}
            points["total"] = points.get("total", 0) + pts
            points.setdefault("achievements", []).extend([{"date": today, "badge": b, "habit": habit_id} for b in badges])
            POINTS_FILE.write_text(json.dumps(points, indent=2))

            print(f"✓ Habit '{habit_id}' checked in! Streak: {streak} days | +{pts} pts" + (f" | Unlocked: {', '.join(badges)}" if badges else ""))
            return

    print(f"Habit '{habit_id}' not found")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("habit_id")
    p.add_argument("--notes", default="")
    args = p.parse_args()
    check(args.habit_id, args.notes)