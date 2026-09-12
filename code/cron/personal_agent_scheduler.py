#!/usr/bin/env python3
"""
Personal Agent Scheduler — runs personal life admin tasks on schedule.

Called by cron with a --mode flag to run specific task groups:
  --mode wellness-checkin    : Evening wellness prompt (daily 9pm)
  --mode habit-review        : Weekly habit review (Sunday 8pm)
  --mode finance-scan        : Scan emails for subscriptions/bills (daily 8am)
  --mode bill-reminder       : Check upcoming bills (daily 7am)
  --mode monthly-finance     : Full monthly finance report (1st of month)
  --mode doc-expiry          : Check document expirations (daily 7am)
  --mode home-maintenance    : Home maintenance reminders (Monday 9am)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
LOG_DIR = HERMES_HOME / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "personal_agent.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_json(path, default=None):
    if default is None:
        default = {}
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_env():
    """Load key=value pairs from ~/.hermes/.env."""
    env_path = HERMES_HOME / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val


def send_telegram(message: str):
    """Send a message via Telegram bot API."""
    load_env()
    import requests as _req

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_HOME_CHANNEL", os.environ.get("TELEGRAM_CHAT_ID", ""))

    if not bot_token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_HOME_CHANNEL not set, skipping")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}

    try:
        resp = _req.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"Telegram API error {resp.status_code}: {resp.text[:200]}")
    except _req.RequestException as e:
        logger.warning(f"Telegram send failed: {e}")


# ── Wellness Check-in ────────────────────────────────────────────────────────

def wellness_checkin():
    """Evening wellness check-in prompt."""
    daily_log = load_json(HERMES_HOME / "wellness/daily_log.json", [])
    today = datetime.now().strftime("%Y-%m-%d")

    # Check if already logged today
    entries = daily_log if isinstance(daily_log, list) else []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("date") == today:
            logger.info("Wellness already logged today, skipping prompt")
            return

    # Pick a random emoji prompt to keep it fresh
    import random
    prompts = [
        ("🌙", "Evening check-in! How was your day?"),
        ("🌆", "Hey — quick check-in. How are you doing?"),
        ("☕", "Wind-down time. How was your day?"),
        ("🌿", "Check-in: how was your day?"),
        ("✨", "Evening! How did today go?"),
    ]
    emoji, greeting = random.choice(prompts)
    send_telegram(
        f"{emoji} {greeting}\n\n"
        "Just reply with:\n"
        "😊 or 😐 or 😴 (mood)\n"
        "⚡ or 🔋 or 🪫 (energy)\n"
        "😴 6h (sleep)\n"
        "🏃 30min (exercise)\n\n"
        "Or just tell me about your day — I'll figure it out!"
    )
    logger.info("Sent wellness check-in prompt")


# ── Habit Review ─────────────────────────────────────────────────────────────

def habit_review():
    """Weekly habit review — every Sunday evening."""
    habits_data = load_json(HERMES_HOME / "habits/habits.json", {})
    habits = habits_data.get("habits", [])
    goals_data = load_json(HERMES_HOME / "habits/goals.json", {})
    goals = goals_data.get("goals", [])

    if not habits:
        logger.info("No habits to review")
        return

    today = datetime.now()
    lines = ["📊 Weekly Habit Review\n"]

    for habit in habits:
        name = habit.get("name", "Unknown")
        streak = habit.get("streak_current", 0)
        longest = habit.get("streak_longest", 0)
        target = habit.get("target_per_week", 7)
        history = habit.get("history", {})

        week_completions = 0
        for i in range(7):
            day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            if day in history and history[day].get("done"):
                week_completions += 1

        pct = int(week_completions / max(target, 1) * 100)
        emoji = "🔥" if pct >= 80 else "👍" if pct >= 50 else "⚠️"
        lines.append(f"{emoji} {name}: {week_completions}/{target} ({pct}%) | Streak: {streak} days")

    if goals:
        lines.append("\n🎯 Goals:")
        for goal in goals:
            name = goal.get("objective", "Unknown")
            progress = goal.get("progress_pct", 0)
            status = goal.get("status", "unknown")
            lines.append(f"  • {name}: {progress}% ({status})")

    send_telegram("\n".join(lines))
    logger.info("Sent weekly habit review")


# ── Bill Reminder ────────────────────────────────────────────────────────────

def bill_reminder():
    """Check for bills due in the next 3 days."""
    bills_data = load_json(HERMES_HOME / "personal/bills.json", {})
    bills = bills_data.get("bills", [])

    if not bills:
        logger.info("No bills to check")
        return

    today = datetime.now()
    upcoming = []
    for bill in bills:
        due_day = bill.get("due_day", 0)
        if not due_day:
            continue
        # Calculate next due date
        if today.day <= due_day:
            due_date = today.replace(day=due_day)
        else:
            # Next month
            if today.month == 12:
                due_date = today.replace(year=today.year + 1, month=1, day=due_day)
            else:
                due_date = today.replace(month=today.month + 1, day=due_day)

        days_until = (due_date - today).days
        if 0 <= days_until <= 3:
            upcoming.append((bill, days_until))

    if not upcoming:
        logger.info("No bills due in next 3 days")
        return

    lines = ["💸 Upcoming Bills:\n"]
    for bill, days in upcoming:
        name = bill.get("name", "Unknown")
        amount = bill.get("amount", 0)
        autopay = " (autopay)" if bill.get("autopay") else ""
        if days == 0:
            lines.append(f"• {name}: ${amount}{autopay} — DUE TODAY")
        elif days == 1:
            lines.append(f"• {name}: ${amount}{autopay} — due tomorrow")
        else:
            lines.append(f"• {name}: ${amount}{autopay} — due in {days} days")

    send_telegram("\n".join(lines))
    logger.info(f"Sent bill reminders for {len(upcoming)} bills")


# ── Document Expiry Check ────────────────────────────────────────────────────

def doc_expiry_check():
    """Check for documents expiring in the next 90 days."""
    docs_data = load_json(HERMES_HOME / "personal/documents.json", {})
    docs = docs_data.get("documents", [])

    if not docs:
        logger.info("No documents to check")
        return

    today = datetime.now()
    expiring = []
    for doc in docs:
        expiry_str = doc.get("expiry", "")
        if not expiry_str:
            continue
        try:
            expiry = datetime.strptime(expiry_str, "%Y-%m-%d")
            days_until = (expiry - today).days
            if 0 <= days_until <= 90:
                expiring.append((doc, days_until))
        except ValueError:
            continue

    if not expiring:
        logger.info("No documents expiring in next 90 days")
        return

    expiring.sort(key=lambda x: x[1])
    lines = ["📄 Documents Expiring Soon:\n"]
    for doc, days in expiring:
        name = doc.get("name", "Unknown")
        expiry = doc.get("expiry", "?")
        if days <= 7:
            lines.append(f"⚠️ {name}: expires {expiry} ({days} days!)")
        elif days <= 30:
            lines.append(f"• {name}: expires {expiry} ({days} days)")
        else:
            lines.append(f"• {name}: expires {expiry} ({days} days)")

    send_telegram("\n".join(lines))
    logger.info(f"Sent document expiry alerts for {len(expiring)} documents")


# ── Monthly Finance Report ───────────────────────────────────────────────────

def monthly_finance_report():
    """Generate and send monthly finance report."""
    subs_data = load_json(HERMES_HOME / "finance/subscriptions.json", {})
    subscriptions = subs_data.get("subscriptions", [])
    bills_data = load_json(HERMES_HOME / "personal/bills.json", {})
    bills = bills_data.get("bills", [])
    budget_data = load_json(HERMES_HOME / "finance/budget.json", {})

    today = datetime.now()
    month_str = today.strftime("%Y-%m")

    active_subs = [s for s in subscriptions if s.get("status") == "active"]
    total_subs = sum(s.get("amount", 0) for s in active_subs if s.get("frequency") == "monthly")
    total_subs += sum(s.get("amount", 0) / 12 for s in active_subs if s.get("frequency") == "yearly")
    total_bills = sum(b.get("amount", 0) for b in bills)

    lines = [f"📊 Monthly Finance Report — {today.strftime('%B %Y')}\n"]
    lines.append(f"💳 Subscriptions: ${total_subs:.2f}/mo ({len(active_subs)} active)")
    lines.append(f"🧾 Bills: ${total_bills:.2f}/mo ({len(bills)} tracked)")
    lines.append(f"📈 Total Fixed: ${total_subs + total_bills:.2f}/mo\n")

    if active_subs:
        lines.append("Active Subscriptions:")
        for s in sorted(active_subs, key=lambda x: x.get("amount", 0), reverse=True):
            lines.append(f"  • {s.get('name', '?')}: ${s.get('amount', 0)}/{s.get('frequency', 'monthly')}")

    # Budget vs actual
    monthly_budget = budget_data.get("monthly_budget", {})
    actuals = budget_data.get("actuals", {}).get(month_str, {})
    if monthly_budget:
        lines.append("\n🎯 Budget vs Actual:")
        for cat, target in monthly_budget.items():
            actual = actuals.get(cat, 0)
            diff = target - actual
            emoji = "✅" if diff >= 0 else "❌"
            lines.append(f"  {emoji} {cat}: ${actual:.0f} / ${target:.0f} (${diff:+.0f})")

    send_telegram("\n".join(lines))
    logger.info("Sent monthly finance report")


# ── Home Maintenance Reminder ────────────────────────────────────────────────

def home_maintenance():
    """Weekly home maintenance check (Monday morning)."""
    home_data = load_json(HERMES_HOME / "personal/home_maintenance.json", {})
    tasks = home_data.get("tasks", [])

    if not tasks:
        logger.info("No home maintenance tasks")
        return

    today = datetime.now()
    upcoming = []
    for task in tasks:
        last_done_str = task.get("last_done", "")
        interval_days = task.get("interval_days", 0)
        if not last_done_str or not interval_days:
            continue
        try:
            last_done = datetime.strptime(last_done_str, "%Y-%m-%d")
            next_due = last_done + timedelta(days=interval_days)
            days_until = (next_due - today).days
            if days_until <= 7:
                upcoming.append((task, days_until))
        except ValueError:
            continue

    if not upcoming:
        logger.info("No home maintenance due this week")
        return

    lines = ["🏠 Home Maintenance This Week:\n"]
    for task, days in upcoming:
        name = task.get("name", "Unknown")
        if days <= 0:
            lines.append(f"⚠️ {name}: OVERDUE by {abs(days)} days")
        elif days <= 2:
            lines.append(f"• {name}: due in {days} days")
        else:
            lines.append(f"• {name}: due in {days} days")

    send_telegram("\n".join(lines))
    logger.info(f"Sent home maintenance reminders for {len(upcoming)} tasks")


# ── Emotional Intelligence ────────────────────────────────────────────────────

def ei_contextual_checkin():
    """Contextual wellness check-in using EI stress detection."""
    ei_script = HERMES_HOME / "scripts" / "emotional_intelligence.py"
    if not ei_script.exists():
        logger.warning("EI script not found, falling back to basic checkin")
        wellness_checkin()
        return

    import subprocess
    result = subprocess.run(
        [sys.executable, str(ei_script), "checkin"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0 and result.stdout.strip():
        send_telegram(result.stdout.strip())
        logger.info("Sent contextual EI check-in")
    else:
        logger.warning("EI checkin failed, falling back to basic")
        wellness_checkin()


def ei_gratitude_prompt():
    """Weekly gratitude journaling prompt."""
    ei_script = HERMES_HOME / "scripts" / "emotional_intelligence.py"
    if not ei_script.exists():
        return

    import subprocess
    result = subprocess.run(
        [sys.executable, str(ei_script), "journal"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0 and result.stdout.strip():
        msg = (
            "📝 *Weekly Gratitude Journal*\n\n"
            + result.stdout.strip()
            + "\n\nReply with your items and I'll log them!"
        )
        send_telegram(msg)
        logger.info("Sent gratitude prompt")


def ei_birthday_reminder():
    """Check for upcoming birthdays and send reminders."""
    ei_script = HERMES_HOME / "scripts" / "emotional_intelligence.py"
    if not ei_script.exists():
        return

    import subprocess
    result = subprocess.run(
        [sys.executable, str(ei_script), "relationships"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return

    # Parse birthdays from output
    lines = result.stdout.strip().split("\n")
    upcoming = []
    in_birthdays = False
    for line in lines:
        if "Upcoming Birthdays" in line:
            in_birthdays = True
            continue
        if "Stale Relationships" in line:
            in_birthdays = False
            continue
        if in_birthdays and line.strip().startswith("-"):
            upcoming.append(line.strip())

    if upcoming:
        msg = "🎂 *Upcoming Birthdays*\n\n" + "\n".join(upcoming)
        send_telegram(msg)
        logger.info(f"Sent birthday reminders for {len(upcoming)} contacts")


def ei_stress_check():
    """Daily stress check — log results, alert if high."""
    ei_script = HERMES_HOME / "scripts" / "emotional_intelligence.py"
    if not ei_script.exists():
        return

    import subprocess
    result = subprocess.run(
        [sys.executable, str(ei_script), "stress"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return

    try:
        data = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return

    level = data.get("overall_stress", "unknown")
    indicators = data.get("indicators", [])

    # Log to state
    state_file = HERMES_HOME / "ei_daily_log.json"
    log_data = load_json(state_file, {"entries": []})
    log_data["entries"].append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "stress_level": level,
        "indicator_count": len(indicators),
    })
    # Keep last 30 days
    log_data["entries"] = log_data["entries"][-30:]
    save_json(state_file, log_data)

    # Alert if high stress
    if level == "high":
        indicator_summary = "\n".join(
            f"  • [{i['level']}] {i['detail']}" for i in indicators[:3]
        )
        send_telegram(
            f"⚠️ *High Stress Detected*\n\n"
            f"Indicators:\n{indicator_summary}\n\n"
            f"Consider taking a break or talking to someone. I'm here if you need anything."
        )
        logger.info("Sent high stress alert")

    logger.info(f"Stress check complete: {level} ({len(indicators)} indicators)")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Personal Agent Scheduler")
    parser.add_argument("--mode", required=True, choices=[
        "wellness-checkin", "habit-review", "bill-reminder",
        "doc-expiry", "monthly-finance", "home-maintenance",
        "ei-checkin", "gratitude-prompt", "birthday-reminder",
        "stress-check",
    ])
    args = parser.parse_args()

    logger.info(f"Running personal agent task: {args.mode}")

    dispatch = {
        "wellness-checkin": wellness_checkin,
        "habit-review": habit_review,
        "bill-reminder": bill_reminder,
        "doc-expiry": doc_expiry_check,
        "monthly-finance": monthly_finance_report,
        "home-maintenance": home_maintenance,
        "ei-checkin": ei_contextual_checkin,
        "gratitude-prompt": ei_gratitude_prompt,
        "birthday-reminder": ei_birthday_reminder,
        "stress-check": ei_stress_check,
    }

    try:
        dispatch[args.mode]()
    except Exception as e:
        logger.error(f"Error running {args.mode}: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
