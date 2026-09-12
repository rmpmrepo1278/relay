#!/usr/bin/env python3
"""personalization.py - Adapt to user's style, preferences, and communication patterns.

Learns how the user likes to communicate, what topics they care about,
when they're available, and adjusts the agent's behavior accordingly.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List
from collections import defaultdict

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
PERSONAL_DB = DATA_DIR / "personalization.db"


def get_db():
    conn = sqlite3.connect(str(PERSONAL_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS user_preferences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        value TEXT NOT NULL,
        confidence REAL DEFAULT 0.5,
        source TEXT DEFAULT 'observed',
        observed_count INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS communication_patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pattern_type TEXT NOT NULL,
        pattern_value TEXT NOT NULL,
        frequency INTEGER DEFAULT 1,
        last_seen TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS topic_interests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL,
        interest_level REAL DEFAULT 0.5,
        interactions INTEGER DEFAULT 1,
        last_interaction TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS active_hours (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hour INTEGER NOT NULL,
        day_of_week TEXT NOT NULL,
        activity_level REAL DEFAULT 0.5,
        message_count INTEGER DEFAULT 1,
        UNIQUE(hour, day_of_week)
    )""")
    conn.commit()
    return conn


def record_preference(key, value, confidence=0.6, source="observed"):
    """Record or update a user preference."""
    conn = get_db()
    now = datetime.now().isoformat()
    existing = conn.execute("SELECT id, observed_count FROM user_preferences WHERE key = ?", (key,)).fetchone()

    if existing:
        conn.execute(
            """UPDATE user_preferences
               SET value = ?, confidence = MAX(confidence, ?), observed_count = ?, updated_at = ?
               WHERE id = ?""",
            (value, confidence, existing["observed_count"] + 1, now, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO user_preferences (key, value, confidence, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (key, value, confidence, source, now, now),
        )
    conn.commit()
    conn.close()


def get_preference(key, default=None):
    conn = get_db()
    try:
        row = conn.execute("SELECT value, confidence FROM user_preferences WHERE key = ?", (key,)).fetchone()
        if row:
            return {"value": row["value"], "confidence": row["confidence"]}
        return {"value": default, "confidence": 0}
    finally:
        conn.close()


def get_all_preferences():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM user_preferences ORDER BY confidence DESC").fetchall()
        return {r["key"]: {"value": r["value"], "confidence": r["confidence"], "count": r["observed_count"]} for r in rows}
    finally:
        conn.close()


def record_communication_pattern(pattern_type, pattern_value):
    """Record a communication pattern (e.g., greeting style, response length preference)."""
    conn = get_db()
    now = datetime.now().isoformat()
    existing = conn.execute(
        "SELECT id, frequency FROM communication_patterns WHERE pattern_type = ? AND pattern_value = ?",
        (pattern_type, pattern_value),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE communication_patterns SET frequency = ?, last_seen = ? WHERE id = ?",
            (existing["frequency"] + 1, now, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO communication_patterns (pattern_type, pattern_value, frequency, last_seen, created_at)
               VALUES (?, ?, 1, ?, ?)""",
            (pattern_type, pattern_value, now, now),
        )
    conn.commit()
    conn.close()


def record_topic_interest(topic, interest_delta=0.1):
    """Record interest in a topic."""
    conn = get_db()
    now = datetime.now().isoformat()
    existing = conn.execute("SELECT id, interest_level, interactions FROM topic_interests WHERE topic = ?", (topic,)).fetchone()

    if existing:
        new_interest = min(1.0, existing["interest_level"] + interest_delta)
        conn.execute(
            "UPDATE topic_interests SET interest_level = ?, interactions = ?, last_interaction = ? WHERE id = ?",
            (new_interest, existing["interactions"] + 1, now, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO topic_interests (topic, interest_level, interactions, last_interaction, created_at)
               VALUES (?, ?, 1, ?, ?)""",
            (topic, 0.5 + interest_delta, now, now),
        )
    conn.commit()
    conn.close()


def record_active_time(hour=None, day_of_week=None):
    """Record when the user is active."""
    if hour is None:
        now = datetime.now()
        hour = now.hour
    if day_of_week is None:
        day_of_week = datetime.now().strftime("%A")

    conn = get_db()
    existing = conn.execute(
        "SELECT id, message_count, activity_level FROM active_hours WHERE hour = ? AND day_of_week = ?",
        (hour, day_of_week),
    ).fetchone()

    if existing:
        new_count = existing["message_count"] + 1
        new_level = min(1.0, existing["activity_level"] + 0.05)
        conn.execute(
            "UPDATE active_hours SET message_count = ?, activity_level = ? WHERE id = ?",
            (new_count, new_level, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO active_hours (hour, day_of_week, activity_level, message_count) VALUES (?, ?, 0.5, 1)",
            (hour, day_of_week),
        )
    conn.commit()
    conn.close()


def get_active_hours():
    """Get when the user is typically active."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT hour, day_of_week, activity_level FROM active_hours ORDER BY activity_level DESC"
        ).fetchall()
        return [{"hour": r["hour"], "day": r["day_of_week"], "level": r["activity_level"]} for r in rows]
    finally:
        conn.close()


def get_top_topics(limit=10):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT topic, interest_level, interactions FROM topic_interests ORDER BY interest_level DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_communication_style():
    """Get the dominant communication patterns."""
    conn = get_db()
    try:
        patterns = {}
        rows = conn.execute(
            """SELECT pattern_type, pattern_value, frequency
               FROM communication_patterns
               ORDER BY frequency DESC"""
        ).fetchall()
        for r in rows:
            if r["pattern_type"] not in patterns:
                patterns[r["pattern_type"]] = r["pattern_value"]
        return patterns
    finally:
        conn.close()


def get_personalization_summary():
    return {
        "preferences": len(get_all_preferences()),
        "topics": len(get_top_topics(100)),
        "active_hours": len(get_active_hours()),
        "communication_patterns": get_communication_style(),
    }


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"

    if cmd == "summary":
        print(json.dumps(get_personalization_summary(), indent=2))
    elif cmd == "prefs":
        for k, v in get_all_preferences().items():
            print(f"  {k}: {v['value']} (confidence: {v['confidence']:.2f}, seen: {v['count']}x)")
    elif cmd == "topics":
        for t in get_top_topics():
            print(f"  {t['topic']}: {t['interest_level']:.2f} ({t['interactions']} interactions)")
    elif cmd == "hours":
        for h in get_active_hours()[:10]:
            print(f"  {h['day']} {h['hour']:02d}:00 — activity: {h['level']:.2f}")
    elif cmd == "style":
        for k, v in get_communication_style().items():
            print(f"  {k}: {v}")
