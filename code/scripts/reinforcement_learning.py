#!/usr/bin/env python3
"""reinforcement_learning.py - Learn from user feedback to improve behavior.

Tracks thumbs up/down, corrections, and preferences to build a reward model
that shapes future behavior. The agent gets better the more you interact with it.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List
from collections import defaultdict

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
RL_DB = DATA_DIR / "reinforcement_learning.db"


def get_db():
    conn = sqlite3.connect(str(RL_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_type TEXT NOT NULL,
        action_detail TEXT DEFAULT '',
        reward REAL NOT NULL,
        context TEXT DEFAULT '{}',
        user_comment TEXT DEFAULT '',
        session_id TEXT,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS action_values (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_type TEXT NOT NULL,
        context_pattern TEXT DEFAULT '*',
        value REAL DEFAULT 0.0,
        visits INTEGER DEFAULT 0,
        avg_reward REAL DEFAULT 0.0,
        last_updated TEXT,
        UNIQUE(action_type, context_pattern)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS preferences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        value TEXT NOT NULL,
        confidence REAL DEFAULT 0.5,
        source TEXT DEFAULT 'feedback',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS reward_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period TEXT NOT NULL,
        total_reward REAL DEFAULT 0,
        action_count INTEGER DEFAULT 0,
        avg_reward REAL DEFAULT 0,
        best_action TEXT,
        worst_action TEXT,
        timestamp TEXT NOT NULL
    )""")
    conn.commit()
    return conn


def record_feedback(action_type, reward, action_detail="", context=None, comment="", session_id=None):
    """Record user feedback (reward: -1.0 to 1.0)."""
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO feedback (action_type, action_detail, reward, context, user_comment, session_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (action_type, action_detail, max(-1.0, min(1.0, reward)),
         json.dumps(context or {}), comment, session_id, now),
    )

    # Update action value (exponential moving average)
    _update_action_value(conn, action_type, context or {}, reward)

    conn.commit()
    conn.close()


def _update_action_value(conn, action_type, context, reward, alpha=0.3):
    """Update estimated value for an action type using exponential moving average."""
    context_pattern = _context_to_pattern(context)
    now = datetime.now().isoformat()

    row = conn.execute(
        "SELECT id, value, visits FROM action_values WHERE action_type = ? AND context_pattern = ?",
        (action_type, context_pattern),
    ).fetchone()

    if row:
        new_value = (1 - alpha) * row["value"] + alpha * reward
        new_visits = row["visits"] + 1
        conn.execute(
            "UPDATE action_values SET value = ?, visits = ?, avg_reward = ?, last_updated = ? WHERE id = ?",
            (new_value, new_visits, new_value, now, row["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO action_values (action_type, context_pattern, value, visits, avg_reward, last_updated)
               VALUES (?, ?, ?, 1, ?, ?)""",
            (action_type, context_pattern, reward, reward, now),
        )


def _context_to_pattern(context):
    """Convert context dict to a searchable pattern."""
    if not context:
        return "*"
    parts = []
    for k in sorted(context.keys()):
        v = context[k]
        if isinstance(v, str) and len(v) < 50:
            parts.append(f"{k}={v}")
    return "|".join(parts[:3]) if parts else "*"


def get_best_actions(context=None, limit=10):
    """Get the highest-value actions."""
    conn = get_db()
    try:
        if context:
            pattern = _context_to_pattern(context)
            rows = conn.execute(
                """SELECT action_type, value, visits, avg_reward
                   FROM action_values
                   WHERE context_pattern = ? OR context_pattern = '*'
                   ORDER BY value DESC LIMIT ?""",
                (pattern, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT action_type, value, visits, avg_reward
                   FROM action_values
                   ORDER BY value DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_worst_actions(limit=10):
    """Get the lowest-value actions to avoid."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT action_type, value, visits, avg_reward
               FROM action_values
               WHERE visits >= 3
               ORDER BY value ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def set_preference(key, value, confidence=0.8):
    """Record a user preference."""
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO preferences (key, value, confidence, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value = ?, confidence = ?, updated_at = ?""",
        (key, str(value), confidence, now, str(value), confidence, now),
    )
    conn.commit()
    conn.close()


def get_preference(key, default=None):
    conn = get_db()
    try:
        row = conn.execute("SELECT value, confidence FROM preferences WHERE key = ?", (key,)).fetchone()
        if row:
            return {"value": row["value"], "confidence": row["confidence"]}
        return {"value": default, "confidence": 0}
    finally:
        conn.close()


def get_all_preferences():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM preferences ORDER BY confidence DESC").fetchall()
        return {r["key"]: {"value": r["value"], "confidence": r["confidence"]} for r in rows}
    finally:
        conn.close()


def get_reward_trend(days=30):
    """Get reward trend over time."""
    conn = get_db()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT DATE(created_at) as day, AVG(reward) as avg_reward, COUNT(*) as cnt
               FROM feedback WHERE created_at > ?
               GROUP BY day ORDER BY day""",
            (cutoff,),
        ).fetchall()
        return [{"date": r["day"], "avg_reward": round(r["avg_reward"], 3), "count": r["cnt"]} for r in rows]
    finally:
        conn.close()


def get_rl_stats():
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as cnt FROM feedback").fetchone()["cnt"]
        positive = conn.execute("SELECT COUNT(*) as cnt FROM feedback WHERE reward > 0").fetchone()["cnt"]
        negative = conn.execute("SELECT COUNT(*) as cnt FROM feedback WHERE reward < 0").fetchone()["cnt"]
        avg = conn.execute("SELECT AVG(reward) as avg FROM feedback").fetchone()["avg"]
        actions = conn.execute("SELECT COUNT(*) as cnt FROM action_values").fetchone()["cnt"]
        prefs = conn.execute("SELECT COUNT(*) as cnt FROM preferences").fetchone()["cnt"]
        return {
            "total_feedback": total, "positive": positive, "negative": negative,
            "avg_reward": round(avg or 0, 3),
            "tracked_actions": actions, "preferences": prefs,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        print(json.dumps(get_rl_stats(), indent=2))
    elif cmd == "best":
        for a in get_best_actions():
            print(f"  {a['action_type']}: {a['value']:.3f} ({a['visits']} visits)")
    elif cmd == "worst":
        for a in get_worst_actions():
            print(f"  {a['action_type']}: {a['value']:.3f} ({a['visits']} visits)")
    elif cmd == "prefs":
        for k, v in get_all_preferences().items():
            print(f"  {k}: {v['value']} (confidence: {v['confidence']})")
    elif cmd == "trend":
        for t in get_reward_trend():
            print(f"  {t['date']}: {t['avg_reward']:.3f} ({t['count']} feedback)")
