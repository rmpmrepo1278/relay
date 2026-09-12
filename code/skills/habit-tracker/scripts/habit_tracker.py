#!/usr/bin/env python3
"""Habit & goal tracker CLI — used by the habit-tracker skill and cron.

Usage:
  habit_tracker.py checkoff <habit_id> [--yesterday|--date YYYY-MM-DD]
  habit_tracker.py log <habit_id> <value> [--date YYYY-MM-DD]
  habit_tracker.py streaks
  habit_tracker.py goals
  habit_tracker.py summary [--format brief|detailed]
  habit_tracker.py daily-prompt   # print today's checklist for Telegram
  habit_tracker.py weekly-review
  habit_tracker.py sync-from-telegram  # parse /checkoff <habit> yes|30 from bridge
"""
import json, sys, os, argparse
from datetime import date, datetime, timedelta
from pathlib import Path

HABITS_DIR = Path.home() / ".hermes" / "habits"
HABITS_FILE = HABITS_DIR / "habits.json"
GOALS_FILE = HABITS_DIR / "goals.json"
DECISIONS_DB = HABITS_DIR / "decisions.db"

def load_json(path, default):
    if not path.exists():
        return default
    with open(path) as f:
        return json.load(f)

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def today_str():
    return date.today().isoformat()

def checkoff(args):
    habits_data = load_json(HABITS_FILE, {"habits": []})
    habit = next((h for h in habits_data["habits"] if h["id"] == args.habit_id), None)
    if not habit:
        return {"text": f"❌ Unknown habit: {args.habit_id}", "exit": 1}

    d = args.date or (date.today() - timedelta(days=1) if args.yesterday else date.today())
    d_str = d.isoformat()

    # Parse value: "yes" → 1.0, "30m" → 30.0, "1.5h" → 90.0, numeric → float
    value = None
    if args.value is not None:
        value = float(args.value)
    elif args.yes_no:
        value = 1.0
    else:
        value = 1.0

    habit["history"][d_str] = value

    # Update streaks
    update_streaks(habit)
    save_json(HABITS_FILE, habits_data)

    streak = habit.get("streak_current", 0)
    unit = habit.get("unit", "times")
    val = habit["history"][d_str]
    msg = f"✅ {habit['name']}: {val}{unit} on {d_str} | streak: {streak}🔥"
    return {"text": msg, "exit": 0}

def _parse_value(val_str):
    """Parse value strings like 'yes', '30m', '1.5h', '45'."""
    val_str = val_str.strip().lower()
    if val_str in ("yes", "done", "y"):
        return 1.0
    if val_str in ("no", "skip", "n"):
        return 0.0
    try:
        return float(val_str)
    except ValueError:
        pass
    # Parse time formats like "30m", "1.5h"
    if val_str.endswith("m"):
        try:
            return float(val_str[:-1])
        except ValueError:
            pass
    if val_str.endswith("h"):
        try:
            return float(val_str[:-1]) * 60
        except ValueError:
            pass
    return 1.0

def update_streaks(habit):
    hist = habit.get("history", {})
    freq = habit.get("frequency", "daily")
    target_per_week = habit.get("target_per_week", 7)

    if freq == "daily":
        today = date.today()
        streak = 0
        for i in range(365):  # check up to a year back
            d = today - timedelta(days=i)
            if d.isoformat() in hist and float(hist[d.isoformat()]) > 0:
                streak += 1
            else:
                break
        habit["streak_current"] = streak
        if streak > habit.get("streak_longest", 0):
            habit["streak_longest"] = streak
    elif freq == "weekly":
        this_week = date.today().isocalendar()[1]
        weeks_done = 0
        for w in range(52):
            target_week = this_week - w
            if target_week < 1:
                break
            week_entries = [v for d, v in hist.items()
                          if date.fromisoformat(d).isocalendar()[1] == target_week]
            if week_entries and sum(week_entries) >= target_per_week:
                weeks_done += 1
            else:
                break
        habit["streak_current"] = weeks_done

def streaks(args):
    habits = load_json(HABITS_FILE, {"habits": []})
    lines = ["🔥 **Habit Streaks**"]
    for h in sorted(habits["habits"], key=lambda x: x.get("streak_current", 0), reverse=True):
        cur = h.get("streak_current", 0)
        long = h.get("streak_longest", 0)
        target = h.get("target_per_week", 7)
        freq = h.get("frequency", "daily")
        icon = "🔥" if cur > 0 else "💀"
        lines.append(f"{icon} {h['name']}: {cur} (best: {long}) — target {target}/{freq}")
    return {"text": "\n".join(lines), "exit": 0}

def goals(args):
    data = load_json(GOALS_FILE, {"goals": []})
    lines = ["🎯 **Goal Progress**"]
    for g in data["goals"]:
        krs = g.get("key_results", [])
        completed = sum(1 for kr in krs if kr.get("current", 0) >= kr.get("target", 1))
        pct = int(sum(kr.get("current", 0) / max(kr.get("target", 1), 1) for kr in krs) / max(len(krs), 1) * 100)
        icon = "✅" if pct >= 100 else "🚧" if pct > 0 else "⏳"
        lines.append(f"{icon} {g['objective']} ({g.get('period', '?')}): {pct}% — {completed}/{len(krs)} KRs done")
        for kr in krs[:3]:
            cur = kr.get("current", 0)
            tgt = kr.get("target", 1)
            lines.append(f"   · {kr['description']}: {cur}/{tgt}")
    return {"text": "\n".join(lines), "exit": 0}

def daily_prompt(args):
    habits = load_json(HABITS_FILE, {"habits": []})
    today = today_str()
    lines = [f"📅 **{today} — Daily Habit Check**"]
    for h in habits["habits"]:
        done = today in h.get("history", {})
        val = h["history"].get(today, 0) if done else 0
        icon = "✅" if float(val) > 0 else "❌"
        target = h.get("target_per_week", 7)
        lines.append(f"{icon} /checkoff {h['id']} yes — {h['name']} (target: {target}x/{h.get('frequency','daily')})")
    return {"text": "\n".join(lines), "exit": 0}

def summary(args):
    fmt = args.format or "brief"
    habits = load_json(HABITS_FILE, {"habits": []})
    goals_data = load_json(GOALS_FILE, {"goals": []})

    total_habits = len(habits["habits"])
    done_today = sum(1 for h in habits["habits"]
                    if today_str() in h.get("history", {}) and float(h["history"][today_str()]) > 0)
    active_streaks = sum(1 for h in habits["habits"] if h.get("streak_current", 0) > 0)

    if fmt == "brief":
        lines = [f"📊 Habits: {done_today}/{total_habits} today | {active_streaks} active streaks"]
    else:
        lines = [
            f"📊 **Daily Summary** ({today_str()})",
            f"Habits: {done_today}/{total_habits} done today",
            f"Active streaks: {active_streaks}/{total_habits}",
        ]
        for h in habits["habits"]:
            cur = h.get("streak_current", 0)
            lines.append(f"  · {h['name']}: streak {cur}🔥")

    # Add goal progress line
    krs = []
    for g in goals_data["goals"]:
        krs.extend(g.get("key_results", []))
    if krs:
        pct = int(sum(kr.get("current", 0) / max(kr.get("target", 1), 1) for kr in krs) / max(len(krs), 1) * 100)
        lines.append(f"🎯 Goals: {pct}% overall")

    return {"text": "\n".join(lines), "exit": 0}

def weekly_review(args):
    habits = load_json(HABITS_FILE, {"habits": []})
    goals_data = load_json(GOALS_FILE, {"goals": []})
    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    lines = ["📅 **Weekly Review**", f"Week of {week_start.isoformat()}"]
    lines.append("")

    # Habit consistency
    lines.append("📈 **Habit Consistency (last 7 days):**")
    for h in habits["habits"]:
        days_done = sum(1 for i in range(7)
                       if (week_start + timedelta(days=i)).isoformat() in h.get("history", {})
                       and float(h["history"].get((week_start + timedelta(days=i)).isoformat(), 0)) > 0)
        pct = int(days_done / 7 * 100)
        icon = "🔥" if pct >= 70 else "⚠️" if pct >= 30 else "💀"
        lines.append(f"  {icon} {h['name']}: {pct}% ({days_done}/7 days)")

    # Goal progress
    lines.append("")
    lines.append("🎯 **Goal Progress:**")
    for g in goals_data["goals"]:
        krs = g.get("key_results", [])
        pct = int(sum(kr.get("current", 0) / max(kr.get("target", 1), 1) for kr in krs) / max(len(krs), 1) * 100)
        lines.append(f"  {g['objective']}: {pct}%")

    # Suggest improvement
    lines.append("")
    lines.append("💡 **Suggestions:**")
    for h in habits["habits"]:
        if h.get("streak_current", 0) == 0:
            target = h.get("target_per_week", 7)
            lines.append(f"  · Start small: {h['name']} — aim for 1x today")
        elif h.get("streak_longest", 0) > h.get("streak_current", 0):
            lines.append(f"  · Rebuild {h['name']} streak — you've done {h['streak_longest']} before!")

    return {"text": "\n".join(lines), "exit": 0}

def main():
    parser = argparse.ArgumentParser(description="Habit & goal tracker")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("checkoff", help="Mark a habit done/lapsed")
    p.add_argument("habit_id")
    p.add_argument("--value", type=float, default=None, help="Numeric value (e.g. minutes)")
    p.add_argument("--yes-no", dest="yes_no", action="store_true", help="Treat as yes/no (1.0)")
    p.add_argument("--yesterday", action="store_true")
    p.add_argument("--date", default=None)
    p.set_defaults(func=checkoff)

    p = sub.add_parser("streaks", help="Show habit streaks")
    p.set_defaults(func=streaks)

    p = sub.add_parser("goals", help="Show goal progress")
    p.set_defaults(func=goals)

    p = sub.add_parser("daily-prompt", help="Print today's checklist")
    p.set_defaults(func=daily_prompt)

    p = sub.add_parser("summary", help="Show daily summary")
    p.add_argument("--format", choices=["brief", "detailed"], default="brief")
    p.set_defaults(func=summary)

    p = sub.add_parser("weekly-review", help="Generate weekly review report")
    p.set_defaults(func=weekly_review)

    args = parser.parse_args()
    result = args.func(args)
    print(result["text"])
    sys.exit(result["exit"])

if __name__ == "__main__":
    main()
