#!/usr/bin/env python3
"""circuit_breaker.py - Protect all external calls with circuit breaker pattern.

When an external service fails repeatedly, stop calling it (open circuit)
and periodically try again (half-open). Prevents cascade failures.
"""

import json
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional
from enum import Enum

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
CB_DB = DATA_DIR / "circuit_breaker.db"


class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, stop calling
    HALF_OPEN = "half_open"  # Testing if recovered


def get_db():
    conn = sqlite3.connect(str(CB_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS circuits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        state TEXT DEFAULT 'closed',
        failure_count INTEGER DEFAULT 0,
        success_count INTEGER DEFAULT 0,
        failure_threshold INTEGER DEFAULT 5,
        recovery_timeout_seconds INTEGER DEFAULT 60,
        last_failure_at TEXT,
        last_success_at TEXT,
        last_state_change TEXT,
        total_calls INTEGER DEFAULT 0,
        total_failures INTEGER DEFAULT 0,
        avg_response_ms REAL DEFAULT 0
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS circuit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        circuit_name TEXT NOT NULL,
        event_type TEXT NOT NULL,
        old_state TEXT,
        new_state TEXT,
        details TEXT DEFAULT '{}',
        timestamp TEXT NOT NULL
    )""")
    conn.commit()
    return conn


def get_or_create_circuit(name, failure_threshold=5, recovery_timeout=60):
    """Get or create a circuit breaker."""
    conn = get_db()
    row = conn.execute("SELECT * FROM circuits WHERE name = ?", (name,)).fetchone()

    if not row:
        now = datetime.now().isoformat()
        conn.execute(
            """INSERT INTO circuits (name, state, failure_threshold, recovery_timeout_seconds, last_state_change)
               VALUES (?, 'closed', ?, ?, ?)""",
            (name, failure_threshold, recovery_timeout, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM circuits WHERE name = ?", (name,)).fetchone()

    conn.close()
    return dict(row)


def record_success(name, response_ms=0):
    """Record a successful call."""
    conn = get_db()
    now = datetime.now().isoformat()

    row = conn.execute("SELECT * FROM circuits WHERE name = ?", (name,)).fetchone()
    if not row:
        conn.close()
        return

    new_success = row["success_count"] + 1
    new_total = row["total_calls"] + 1
    new_avg = (row["avg_response_ms"] * row["total_calls"] + response_ms) / new_total

    updates = {
        "success_count": new_success,
        "failure_count": 0,  # Reset failure count on success
        "total_calls": new_total,
        "avg_response_ms": new_avg,
        "last_success_at": now,
    }

    old_state = row["state"]

    # Transition from half_open to closed on success
    if row["state"] == "half_open":
        updates["state"] = "closed"
        updates["last_state_change"] = now
        _log_event(conn, name, "half_open_to_closed", old_state, "closed")

    conn.execute(
        """UPDATE circuits SET success_count = ?, failure_count = ?, total_calls = ?,
           avg_response_ms = ?, last_success_at = ?,
           state = COALESCE(?, state), last_state_change = COALESCE(?, last_state_change)
           WHERE name = ?""",
        (new_success, 0, new_total, new_avg, now,
         updates.get("state"), updates.get("last_state_change"), name),
    )
    conn.commit()
    conn.close()


def record_failure(name, error=""):
    """Record a failed call."""
    conn = get_db()
    now = datetime.now().isoformat()

    row = conn.execute("SELECT * FROM circuits WHERE name = ?", (name,)).fetchone()
    if not row:
        conn.close()
        return

    new_failure = row["failure_count"] + 1
    new_total = row["total_calls"] + 1
    old_state = row["state"]

    new_state = old_state

    # Open circuit if threshold exceeded
    if old_state == "closed" and new_failure >= row["failure_threshold"]:
        new_state = "open"
        _log_event(conn, name, "closed_to_open", old_state, new_state,
                   {"error": error, "failures": new_failure})
    elif old_state == "half_open":
        new_state = "open"
        _log_event(conn, name, "half_open_to_open", old_state, new_state,
                   {"error": error})

    conn.execute(
        """UPDATE circuits SET failure_count = ?, total_calls = ?,
           last_failure_at = ?, state = ?, last_state_change = CASE WHEN ? != ? THEN ? ELSE last_state_change END
           WHERE name = ?""",
        (new_failure, new_total, now, new_state, new_state, old_state, now, name),
    )
    conn.commit()
    conn.close()


def allow_request(name):
    """Check if a request should be allowed through."""
    conn = get_db()
    row = conn.execute("SELECT * FROM circuits WHERE name = ?", (name,)).fetchone()
    conn.close()

    if not row:
        return True

    if row["state"] == "closed":
        return True

    if row["state"] == "open":
        # Check if recovery timeout has elapsed
        if row["last_failure_at"]:
            last_fail = datetime.fromisoformat(row["last_failure_at"])
            if (datetime.now() - last_fail).total_seconds() > row["recovery_timeout_seconds"]:
                # Transition to half_open
                _transition_to_half_open(name)
                return True
        return False

    if row["state"] == "half_open":
        return True  # Allow one test request

    return True


def _transition_to_half_open(name):
    """Transition circuit to half-open state."""
    conn = get_db()
    now = datetime.now().isoformat()
    row = conn.execute("SELECT state FROM circuits WHERE name = ?", (name,)).fetchone()
    if row:
        old_state = row["state"]
        conn.execute(
            "UPDATE circuits SET state = 'half_open', last_state_change = ? WHERE name = ?",
            (now, name),
        )
        _log_event(conn, name, f"{old_state}_to_half_open", old_state, "half_open")
    conn.commit()
    conn.close()


def _log_event(conn, name, event_type, old_state, new_state, details=None):
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO circuit_events (circuit_name, event_type, old_state, new_state, details, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, event_type, old_state, new_state, json.dumps(details or {}), now),
    )


def get_all_circuits():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM circuits ORDER BY name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_circuit_events(name=None, limit=20):
    conn = get_db()
    try:
        if name:
            rows = conn.execute(
                "SELECT * FROM circuit_events WHERE circuit_name = ? ORDER BY timestamp DESC LIMIT ?",
                (name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM circuit_events ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def reset_circuit(name):
    """Manually reset a circuit to closed state."""
    conn = get_db()
    now = datetime.now().isoformat()
    row = conn.execute("SELECT state FROM circuits WHERE name = ?", (name,)).fetchone()
    if row:
        old_state = row["state"]
        conn.execute(
            "UPDATE circuits SET state = 'closed', failure_count = 0, last_state_change = ? WHERE name = ?",
            (now, name),
        )
        _log_event(conn, name, f"{old_state}_to_closed_manual", old_state, "closed")
    conn.commit()
    conn.close()


def get_cb_stats():
    conn = get_db()
    try:
        circuits = conn.execute("SELECT * FROM circuits").fetchall()
        open_count = sum(1 for c in circuits if c["state"] == "open")
        half_open = sum(1 for c in circuits if c["state"] == "half_open")
        total_calls = sum(c["total_calls"] for c in circuits)
        total_failures = sum(c["total_failures"] for c in circuits)
        return {
            "total_circuits": len(circuits),
            "closed": len(circuits) - open_count - half_open,
            "open": open_count,
            "half_open": half_open,
            "total_calls": total_calls,
            "total_failures": total_failures,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        print(json.dumps(get_cb_stats(), indent=2))
    elif cmd == "circuits":
        for c in get_all_circuits():
            print(f"  [{c['state']}] {c['name']}: {c['failure_count']} failures, {c['total_calls']} calls")
    elif cmd == "events":
        for e in get_circuit_events():
            print(f"  [{e['event_type']}] {e['circuit_name']}: {e['old_state']} -> {e['new_state']}")
    elif cmd == "reset" and len(sys.argv) > 2:
        reset_circuit(sys.argv[2])
        print(f"  Reset {sys.argv[2]}")
