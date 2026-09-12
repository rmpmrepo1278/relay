#!/usr/bin/env python3
"""commitment_executor.py — Enforce commitments with deadline tracking.

Runs every 5 minutes. Checks for:
  - Overdue commitments (past deadline, not fulfilled) → escalate to Telegram
  - Due-soon commitments (within 30 min of deadline) → gentle reminder
  - Stale commitments (no update in 7+ days) → flag for review

Integrates with commitment_tracker.py for storage and alerts_inbox for Telegram.
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
sys.path.insert(0, str(HERMES_HOME / "scripts"))

try:
    from commitment_tracker import load_commitments, save_commitments
except ImportError:
    load_commitments = None
    save_commitments = None

ALERTS_INBOX = Path.home() / ".hermes" / "data" / "alerts_inbox.jsonl"
STATE_FILE = HERMES_HOME / "data" / "commitment_executor_state.json"
DATA_FILE = HERMES_HOME / "data" / "commitments.json"
OLD_DATA_FILE = HERMES_HOME / "commitments.json"


def push_alert(message, severity="warning"):
    entry = {
        "severity": severity,
        "message": message,
        "source": "commitment_executor",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "delivered": False,
        "requires_approval": False,
        "actions": [],
    }
    try:
        ALERTS_INBOX.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if ALERTS_INBOX.exists():
            content = ALERTS_INBOX.read_text().strip()
            if content:
                existing = json.loads(content) if content.startswith("[") else []
        existing.append(entry)
        ALERTS_INBOX.write_text(json.dumps(existing, indent=2))
    except OSError:
        pass


def load_commitments_from_data():
    """Load from data/commitments.json (new system) or commitments.json (old system)."""
    for path in [DATA_FILE, OLD_DATA_FILE]:
        if path.exists():
            try:
                data = json.loads(path.read_text())
                if isinstance(data, dict):
                    if "active" in data:
                        return data
                    if "commitments" in data:
                        return {"active": data["commitments"], "history": []}
                return data
            except (json.JSONDecodeError, OSError):
                pass
    return {"active": [], "history": []}


def check_commitments():
    now = datetime.now(timezone.utc)
    state = {"last_run": None, "last_overdue_count": 0}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    data = load_commitments_from_data()
    active = data.get("active", [])
    if not active:
        state["last_run"] = now.isoformat()
        STATE_FILE.write_text(json.dumps(state, indent=2))
        print("No active commitments")
        return

    overdue = []
    due_soon = []
    stale = []

    for c in active:
        text = c.get("text", c.get("action", ""))
        deadline_str = c.get("deadline")
        status = c.get("status", "active")
        created_str = c.get("created", c.get("created_at", ""))

        if status != "active":
            continue

        if deadline_str:
            try:
                deadline = datetime.fromisoformat(deadline_str)
                if now > deadline:
                    overdue.append((c, (now - deadline).total_seconds() / 60))
                elif 0 <= (deadline - now).total_seconds() <= 1800:
                    due_soon.append((c, (deadline - now).total_seconds() / 60))
            except ValueError:
                pass

        if created_str:
            try:
                created = datetime.fromisoformat(created_str)
                if (now - created).days >= 7:
                    stale.append(c)
            except ValueError:
                pass

    if overdue:
        msg_lines = ["\u23f3 Overdue Commitments"]
        for c, mins in sorted(overdue, key=lambda x: -x[1]):
            text = c.get("text", c.get("action", "unknown"))[:100]
            source = c.get("source", "unknown")
            msg_lines.append(f"  \u2022 \"{text}\" ({source}) - overdue by {int(mins)}m")
        push_alert("\n".join(msg_lines), severity="critical")
        print(f"Alerted {len(overdue)} overdue commitments")

    if due_soon:
        msg_lines = ["\u23f1 Due Soon"]
        for c, mins in due_soon:
            text = c.get("text", c.get("action", "unknown"))[:100]
            msg_lines.append(f"  \u2022 \"{text}\" - due in {int(mins)}m")
        push_alert("\n".join(msg_lines), severity="info")

    state["last_run"] = now.isoformat()
    state["last_overdue_count"] = len(overdue)
    STATE_FILE.write_text(json.dumps(state, indent=2))

    print(f"Checked {len(active)} commitments: {len(overdue)} overdue, {len(due_soon)} due soon, {len(stale)} stale")


if __name__ == "__main__":
    check_commitments()
