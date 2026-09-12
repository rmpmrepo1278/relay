#!/usr/bin/env python3
"""commitment_tracker.py — Track commitments made in conversations for follow-through."""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

HERMES_HOME = Path.home() / ".hermes"
DATA_FILE = HERMES_HOME / "data" / "commitments.json"

DATA_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_commitments() -> dict:
    """Load commitments from storage."""
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return {"active": [], "history": [], "stats": {
        "total_made": 0, "total_fulfilled": 0,
        "total_failed": 0, "total_overdue": 0, "on_time_rate": 0.0
    }}


def save_commitments(data: dict):
    """Save commitments to storage."""
    DATA_FILE.write_text(json.dumps(data, indent=2))


def _generate_id() -> str:
    return f"c_{int(datetime.now().timestamp())}"


def add_commitment(text: str, deadline: Optional[str] = None, 
                   source: str = "unknown", context: str = "") -> dict:
    """Add a new commitment."""
    data = load_commitments()
    commitment = {
        "id": _generate_id(),
        "text": text,
        "deadline": deadline,
        "source": source,
        "context": context,
        "status": "active",
        "created": datetime.now(timezone.utc).isoformat()
    }
    data["active"].append(commitment)
    data["stats"]["total_made"] = data["stats"].get("total_made", 0) + 1
    save_commitments(data)
    return commitment


def extract_commitments(message: str) -> list[dict]:
    """Extract commitment-like phrases from a message."""
    patterns = [
        r"(?:I'll|I will|I'm going to|I plan to)\s+(.+?)(?:\s+in\s+(.+?))?(?:\s+\.|$)",
        r"(?:Will|Gonna|gonna)\s+(.+?)(?:\s+by\s+(.+?))?(?:\s+\.|$)",
        r"(?:Promise|PROMISE)s?\s+(.+?)(?:\s+\.|$)",
    ]
    results = []
    for p in patterns:
        match = re.search(p, message, re.IGNORECASE)
        if match:
            results.append({"text": match.group(1).strip(), "deadline": match.group(2)})
    return results


def check_overdue(minutes_ahead: int = 30) -> list[dict]:
    """Return commitments due soon or overdue."""
    data = load_commitments()
    now = datetime.now(timezone.utc)
    soon = now + timedelta(minutes=minutes_ahead)
    overdue = []
    for c in data["active"]:
        if c.get("deadline"):
            try:
                deadline = datetime.fromisoformat(c["deadline"].replace("Z", "+00:00"))
                if deadline <= soon:
                    overdue.append(c)
            except Exception:
                pass
    return overdue


def get_upcoming(hours: int = 24) -> list[dict]:
    """Return commitments due in next N hours."""
    return check_overdue(minutes_ahead=hours * 60)


def fulfill_commitment(commitment_id: str, note: str = "") -> Optional[dict]:
    """Mark a commitment as fulfilled."""
    data = load_commitments()
    for i, c in enumerate(data["active"]):
        if c["id"] == commitment_id:
            c["status"] = "fulfilled"
            c["fulfilled"] = datetime.now(timezone.utc).isoformat()
            on_time = False
            if c.get("deadline"):
                try:
                    deadline = datetime.fromisoformat(c["deadline"].replace("Z", "+00:00"))
                    on_time = datetime.now(timezone.utc) <= deadline
                except Exception:
                    pass
            c["on_time"] = on_time
            if note:
                c["note"] = note
            data["history"].append(c)
            del data["active"][i]
            data["stats"]["total_fulfilled"] = data["stats"].get("total_fulfilled", 0) + 1
            if on_time:
                pass
            save_commitments(data)
            return c
    return None


def get_status() -> dict:
    """Return commitment status summary."""
    data = load_commitments()
    total = data["stats"].get("total_made", 0)
    fulfilled = data["stats"].get("total_fulfilled", 0)
    rate = (fulfilled / total * 100) if total > 0 else 0.0
    data["stats"]["on_time_rate"] = round(rate, 1)
    save_commitments(data)
    return {
        "active_count": len(data["active"]),
        "history_count": len(data["history"]),
        "stats": data["stats"],
        "upcoming": check_overdue()
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        print(json.dumps(get_status(), indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "--overdue":
        print(json.dumps(check_overdue(), indent=2))