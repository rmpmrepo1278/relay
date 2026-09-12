#!/usr/bin/env python3
# habit-gamification adapt.py — Adaptive habit difficulty based on performance
# ponytail: read habits.json, analyze patterns, suggest adjustments

import json
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import Counter

HABITS_FILE = Path.home() / ".hermes/habits/habits.json"

def analyze(habit_id: str = None):
    habits = json.loads(HABITS_FILE.read_text())
    suggestions = []

    for h in habits.get("habits", []):
        if habit_id and h.get("id") != habit_id:
            continue

        name = h.get("name", "")
        history = h.get("history", {})

        # Last 7 days check
        recent = [(k, v) for k, v in history.items() if date.fromisoformat(k) > date.today() - timedelta(days=7)]
        if len(recent) < 4:  # Less than 4 days hit in last week
            suggestions.append(f"🔻 '{name}': Only {len(recent)}/7 days hit recently. Consider lowering target.")

        # Streak warning
        streak = h.get("streak_current", 0)
        if streak == 0 and len(recent) == 0:
            suggestions.append(f"💤 '{name}': Streak broken, no activity in 7 days. Suggest: attach to existing streak.")

    if suggestions:
        for s in suggestions:
            print(s)
    else:
        print("✓ All habits on track. No adaptive adjustments needed.")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--habit")
    args = p.parse_args()
    analyze(args.habit)