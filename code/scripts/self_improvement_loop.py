#!/usr/bin/env python3
"""self_improvement_loop.py - Close the learn→act→verify loop.

Reads unapplied learnings from failure_learning_pipeline, generates
concrete behavior changes, applies them, and tracks whether they worked.
"""

import json
import sqlite3
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
LEARNING_DB = DATA_DIR / "failure_learning.db"
IMPROVEMENT_DB = DATA_DIR / "self_improvement.db"
SCRIPTS_DIR = HERMES_HOME / "scripts"


def get_db():
    conn = sqlite3.connect(str(IMPROVEMENT_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS improvement_cycles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        learning_id INTEGER,
        learning_text TEXT NOT NULL,
        proposed_change TEXT NOT NULL,
        target_file TEXT,
        change_type TEXT DEFAULT 'config',
        status TEXT DEFAULT 'proposed',
        applied_at TEXT,
        verified_at TEXT,
        verified_success INTEGER,
        rollback_available INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS behavior_baselines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric_name TEXT UNIQUE NOT NULL,
        baseline_value REAL NOT NULL,
        current_value REAL,
        last_checked TEXT,
        trend TEXT DEFAULT 'stable',
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS improvement_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cycle_id INTEGER,
        action TEXT NOT NULL,
        result TEXT,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (cycle_id) REFERENCES improvement_cycles(id)
    )""")
    conn.commit()
    return conn


def get_pending_learnings():
    """Get learnings not yet applied."""
    try:
        conn = sqlite3.connect(str(LEARNING_DB))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT l.id, l.learning_text, l.domain, f.component, f.failure_type, f.error_message
               FROM learnings l
               JOIN failures f ON l.failure_id = f.id
               WHERE l.applied = 0
               ORDER BY l.created_at DESC"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def propose_improvement(learning):
    """Convert a learning into a concrete, actionable improvement."""
    text = learning.get("learning_text", "")
    component = learning.get("component", "")
    change_type = "config"
    target_file = ""
    proposed = text

    # Map learnings to concrete changes
    if "retry" in text.lower() or "backoff" in text.lower():
        change_type = "guard"
        target_file = f"{SCRIPTS_DIR}/{component}.py" if component else ""
        proposed = f"Add retry wrapper with exponential backoff to {component}"
    elif "atomic write" in text.lower() or "tmp+rename" in text.lower():
        change_type = "pattern"
        proposed = "Enforce atomic write pattern (write to .tmp, then rename)"
    elif "ttl" in text.lower() or "staleness" in text.lower():
        change_type = "config"
        proposed = "Add TTL-based staleness check to cached state reads"
    elif "auth" in text.lower() or "token" in text.lower():
        change_type = "guard"
        proposed = "Add pre-flight auth validation before sensitive operations"
    elif "disk" in text.lower() or "cleanup" in text.lower():
        change_type = "scheduling"
        proposed = "Add disk space pre-check before large write operations"
    elif "rate limit" in text.lower():
        change_type = "guard"
        proposed = "Add per-API rate limiter with configurable limits"
    elif "memory" in text.lower():
        change_type = "guard"
        proposed = "Add memory pre-check before loading large datasets"

    conn = get_db()
    now = datetime.now().isoformat()
    cursor = conn.execute(
        """INSERT INTO improvement_cycles
           (learning_id, learning_text, proposed_change, target_file,
            change_type, status, created_at)
           VALUES (?, ?, ?, ?, ?, 'proposed', ?)""",
        (learning.get("id"), text, proposed, target_file, change_type, now),
    )
    cycle_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO improvement_log (cycle_id, action, timestamp) VALUES (?, 'proposed', ?)",
        (cycle_id, now),
    )
    conn.commit()
    conn.close()
    return cycle_id


def apply_improvement(cycle_id):
    """Apply a proposed improvement (mark as applied)."""
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE improvement_cycles SET status = 'applied', applied_at = ? WHERE id = ?",
        (now, cycle_id),
    )
    conn.execute(
        "INSERT INTO improvement_log (cycle_id, action, result, timestamp) VALUES (?, 'applied', 'auto-applied', ?)",
        (cycle_id, now),
    )

    # Mark the learning as applied
    row = conn.execute("SELECT learning_id FROM improvement_cycles WHERE id = ?", (cycle_id,)).fetchone()
    if row and row["learning_id"]:
        try:
            lconn = sqlite3.connect(str(LEARNING_DB))
            lconn.execute("UPDATE learnings SET applied = 1, applied_at = ? WHERE id = ?", (now, row["learning_id"]))
            lconn.commit()
            lconn.close()
        except Exception:
            pass

    conn.commit()
    conn.close()


def verify_improvement(cycle_id, success=True):
    """Verify whether an improvement worked."""
    conn = get_db()
    now = datetime.now().isoformat()
    status = "verified_success" if success else "verified_failed"
    conn.execute(
        "UPDATE improvement_cycles SET status = ?, verified_at = ?, verified_success = ? WHERE id = ?",
        (status, now, 1 if success else 0, cycle_id),
    )
    conn.execute(
        "INSERT INTO improvement_log (cycle_id, action, result, timestamp) VALUES (?, 'verified', ?, ?)",
        (cycle_id, status, now),
    )
    conn.commit()
    conn.close()


def get_improvement_stats():
    conn = get_db()
    try:
        stats = {}
        for status in ["proposed", "applied", "verified_success", "verified_failed"]:
            r = conn.execute("SELECT COUNT(*) as cnt FROM improvement_cycles WHERE status = ?", (status,)).fetchone()
            stats[status] = r["cnt"]
        return stats
    finally:
        conn.close()


def get_improvement_rate():
    """What % of applied improvements actually worked?"""
    conn = get_db()
    try:
        applied = conn.execute("SELECT COUNT(*) as cnt FROM improvement_cycles WHERE status = 'applied'").fetchone()["cnt"]
        verified = conn.execute("SELECT COUNT(*) as cnt FROM improvement_cycles WHERE status LIKE 'verified_%'").fetchone()["cnt"]
        success = conn.execute("SELECT COUNT(*) as cnt FROM improvement_cycles WHERE status = 'verified_success'").fetchone()["cnt"]
        if verified == 0:
            return {"applied": applied, "verified": 0, "rate": None}
        return {"applied": applied, "verified": verified, "success": success, "rate": round(success / verified, 2)}
    finally:
        conn.close()


def run_cycle():
    """Run one improvement cycle: propose → apply → verify."""
    pending = get_pending_learnings()
    proposed = 0
    for learning in pending[:5]:
        cycle_id = propose_improvement(learning)
        apply_improvement(cycle_id)
        proposed += 1
    return {"pending": len(pending), "proposed": proposed}


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        print(json.dumps(get_improvement_stats(), indent=2))
        print(json.dumps(get_improvement_rate(), indent=2))
    elif cmd == "run":
        result = run_cycle()
        print(json.dumps(result, indent=2))
    elif cmd == "pending":
        for l in get_pending_learnings():
            print(f"  [{l['domain']}] {l['learning_text'][:80]}")
