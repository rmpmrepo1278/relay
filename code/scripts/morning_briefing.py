#!/usr/bin/env python3
"""morning_briefing.py — Generates daily briefing data as JSON.

Reads the latest journal, scheduler state, proactive briefing, and task queue,
then outputs structured JSON for n8n Morning Briefing workflow to deliver.
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"


def read_json(path):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        return None
    return None


def generate_briefing():
    now = datetime.now(timezone.utc)
    sections = []

    # Latest journal entry
    journal_dir = HERMES_HOME / "collaborator-memory" / "journal"
    if journal_dir.exists():
        journals = sorted(journal_dir.glob("*.md"))
        if journals:
            last = journals[-1]
            content = last.read_text()
            first_line = [l for l in content.split("\n") if l.strip() and not l.startswith("#") and not l.startswith("**")]
            if first_line:
                sections.append({"header": "Latest Journal", "body": first_line[0][:80]})

    # Proactive briefing
    brief = read_json(HERMES_HOME / "data" / "proactive_briefing.json")
    if brief and brief.get("briefing", {}).get("pushed"):
        ts = brief.get("timestamp", "")
        if ts:
            sections.append({"header": "Proactive Briefing", "body": f"Sent at {ts[11:16]} UTC"})

    # Scheduler health
    state = read_json(HERMES_HOME / "data" / "scheduler_state.json")
    if state:
        results = {k: v for k, v in state.items() if isinstance(v, dict) and "last_status" in v}
        successes = sum(1 for v in results.values() if v.get("last_status") == "success")
        failures = sum(1 for v in results.values() if v.get("last_status") != "success")
        sections.append({"header": "Scheduler", "body": f"{state.get('jobs_run_count', 0)} runs, {failures} failures"})

    # Task queue
    queue = read_json(HERMES_HOME / "state" / "task_queue.json")
    if queue:
        tasks = queue.get("tasks", [])
        pending = len([t for t in tasks if t.get("status") == "pending"])
        escalated = len([t for t in tasks if t.get("status") == "escalated"])
        if pending or escalated:
            sections.append({"header": "Tasks", "body": f"{pending} pending, {escalated} escalated"})

    # Interest profile
    profile = read_json(HERMES_HOME / "data" / "interest_profile.json")
    if profile and profile.get("dominant"):
        sections.append({"header": "Focus", "body": profile["dominant"]})

    if not sections:
        sections.append({"header": "Status", "body": "No new signals yet."})

    report = {
        "type": "morning_briefing",
        "generated_at": now.isoformat(),
        "date": now.strftime("%a %b %d"),
        "sections": sections
    }

    return report


if __name__ == "__main__":
    report = generate_briefing()
    print(json.dumps(report, indent=2))
