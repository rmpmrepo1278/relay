#!/usr/bin/env python3
"""self_model.py - Track capabilities, success rates, and limitations.

Maintains a self-model that tracks what Hermes can do, what it's good at,
what it struggles with, and what capabilities have changed over time.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
SELF_MODEL_DB = DATA_DIR / "self_model.db"


def get_self_model_db():
    """Get or create the self-model database."""
    conn = sqlite3.connect(str(SELF_MODEL_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS capabilities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        domain TEXT NOT NULL,
        success_rate REAL DEFAULT 0.5,
        attempts INTEGER DEFAULT 0,
        successes INTEGER DEFAULT 0,
        last_attempted TEXT,
        last_succeeded TEXT,
        notes TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS capability_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        capability_id INTEGER NOT NULL,
        success INTEGER NOT NULL,
        context TEXT,
        error TEXT,
        duration_seconds REAL,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (capability_id) REFERENCES capabilities(id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS limitations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT NOT NULL,
        domain TEXT,
        discovered_at TEXT NOT NULL,
        impact TEXT DEFAULT 'medium',
        workaround TEXT,
        status TEXT DEFAULT 'active'
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS meta_goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        goal TEXT NOT NULL,
        category TEXT NOT NULL,
        priority INTEGER DEFAULT 0,
        progress REAL DEFAULT 0.0,
        notes TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    conn.commit()
    return conn


def record_attempt(capability_name, domain, success, context="", error="", duration=0.0):
    """Record an attempt at a capability."""
    conn = get_self_model_db()
    now = datetime.now().isoformat()

    # Upsert capability
    row = conn.execute(
        "SELECT id, attempts, successes FROM capabilities WHERE name = ?",
        (capability_name,),
    ).fetchone()

    if row:
        cap_id = row["id"]
        new_attempts = row["attempts"] + 1
        new_successes = row["successes"] + (1 if success else 0)
        new_rate = new_successes / new_attempts if new_attempts > 0 else 0.5

        conn.execute(
            """UPDATE capabilities
               SET attempts = ?, successes = ?, success_rate = ?,
                   last_attempted = ?, status = 'active',
                   updated_at = ?
               WHERE id = ?""",
            (new_attempts, new_successes, new_rate, now, now, now, cap_id),
        )
        if success:
            conn.execute(
                "UPDATE capabilities SET last_succeeded = ? WHERE id = ?",
                (now, cap_id),
            )
    else:
        cursor = conn.execute(
            """INSERT INTO capabilities
               (name, domain, success_rate, attempts, successes,
                last_attempted, last_succeeded, status, created_at, updated_at)
               VALUES (?, ?, ?, 1, ?, ?, ?, 'active', ?, ?)""",
            (capability_name, domain, 1.0 if success else 0.0,
             1 if success else 0, now if success else None,
             now, now, now),
        )
        cap_id = cursor.lastrowid

    # Log the attempt
    conn.execute(
        """INSERT INTO capability_log
           (capability_id, success, context, error, duration_seconds, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (cap_id, 1 if success else 0, context, error, duration, now),
    )

    conn.commit()
    conn.close()
    return cap_id


def record_limitation(description, domain="", impact="medium", workaround=""):
    """Record a known limitation."""
    conn = get_self_model_db()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO limitations (description, domain, discovered_at, impact, workaround, status)
           VALUES (?, ?, ?, ?, ?, 'active')""",
        (description, domain, now, impact, workaround),
    )
    conn.commit()
    conn.close()


def get_capability_summary():
    """Get summary of all capabilities."""
    conn = get_self_model_db()
    try:
        rows = conn.execute(
            """SELECT name, domain, success_rate, attempts, successes,
                      last_attempted, last_succeeded, status
               FROM capabilities ORDER BY success_rate DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_weak_areas(min_attempts=5, max_success_rate=0.7):
    """Find capabilities that need improvement."""
    conn = get_self_model_db()
    try:
        rows = conn.execute(
            """SELECT name, domain, success_rate, attempts
               FROM capabilities
               WHERE attempts >= ? AND success_rate < ?
               ORDER BY success_rate ASC""",
            (min_attempts, max_success_rate),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_learning_trend(capability_name, days=30):
    """Get success rate trend over time for a capability."""
    conn = get_self_model_db()
    try:
        row = conn.execute(
            "SELECT id FROM capabilities WHERE name = ?", (capability_name,)
        ).fetchone()
        if not row:
            return []

        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT success, timestamp
               FROM capability_log
               WHERE capability_id = ? AND timestamp > ?
               ORDER BY timestamp ASC""",
            (row["id"], cutoff),
        ).fetchall()

        # Calculate rolling success rate
        results = []
        total = 0
        successes = 0
        for r in rows:
            total += 1
            successes += r["success"]
            rate = successes / total if total > 0 else 0
            results.append({
                "timestamp": r["timestamp"],
                "rolling_rate": round(rate, 3),
                "success": r["success"],
            })
        return results
    finally:
        conn.close()


def get_active_limitations():
    """Get all active limitations."""
    conn = get_self_model_db()
    try:
        rows = conn.execute(
            "SELECT * FROM limitations WHERE status = 'active' ORDER BY impact DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_meta_goal(goal, category, priority=0):
    """Add a meta-goal (something to improve about oneself)."""
    conn = get_self_model_db()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO meta_goals (goal, category, priority, progress, status, created_at, updated_at)
           VALUES (?, ?, ?, 0.0, 'active', ?, ?)""",
        (goal, category, priority, now, now),
    )
    conn.commit()
    conn.close()


def update_goal_progress(goal_id, progress, notes=""):
    """Update progress on a meta-goal."""
    conn = get_self_model_db()
    now = datetime.now().isoformat()
    status = "completed" if progress >= 1.0 else "active"
    conn.execute(
        "UPDATE meta_goals SET progress = ?, notes = ?, status = ?, updated_at = ? WHERE id = ?",
        (progress, notes, status, now, goal_id),
    )
    conn.commit()
    conn.close()


def get_meta_goals():
    """Get all meta-goals."""
    conn = get_self_model_db()
    try:
        rows = conn.execute(
            "SELECT * FROM meta_goals WHERE status = 'active' ORDER BY priority DESC, progress ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"

    if cmd == "summary":
        caps = get_capability_summary()
        weak = get_weak_areas()
        limits = get_active_limitations()
        goals = get_meta_goals()

        print(f"Capabilities: {len(caps)}")
        print(f"Weak areas (< 70% with 5+ attempts): {len(weak)}")
        print(f"Active limitations: {len(limits)}")
        print(f"Meta-goals: {len(goals)}")

        if weak:
            print("\nNeeds improvement:")
            for w in weak:
                print(f"  {w['name']}: {w['success_rate']:.0%} ({w['attempts']} attempts)")

        if limits:
            print("\nLimitations:")
            for l in limits:
                print(f"  [{l['impact']}] {l['description']}")

    elif cmd == "record" and len(sys.argv) > 4:
        name = sys.argv[2]
        domain = sys.argv[3]
        success = sys.argv[4].lower() == "true"
        record_attempt(name, domain, success)
        print(f"Recorded attempt for {name}")

    elif cmd == "trend" and len(sys.argv) > 2:
        trend = get_learning_trend(sys.argv[2])
        for t in trend:
            print(f"  {t['timestamp']}: {t['rolling_rate']:.1%}")
