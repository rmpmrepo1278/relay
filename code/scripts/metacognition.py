#!/usr/bin/env python3
"""metacognition.py - Reflect on reasoning, decisions, and cognitive patterns.

The agent should be able to ask: "Why did I decide this? Was I right?
What cognitive biases might I be exhibiting? What would I do differently?"
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
META_DB = DATA_DIR / "metacognition.db"


def get_db():
    conn = sqlite3.connect(str(META_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS reflections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        event_id TEXT,
        event_description TEXT NOT NULL,
        reasoning_used TEXT DEFAULT '',
        decision_made TEXT DEFAULT '',
        outcome TEXT DEFAULT '',
        was_correct INTEGER,
        cognitive_bias TEXT,
        alternative_approach TEXT,
        lesson_learned TEXT,
        confidence_before REAL,
        confidence_after REAL,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS reasoning_chains (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT,
        chain TEXT NOT NULL,
        conclusion TEXT NOT NULL,
        validity_score REAL DEFAULT 0.5,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS cognitive_biases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bias_name TEXT NOT NULL,
        description TEXT NOT NULL,
        occurrences INTEGER DEFAULT 0,
        last_detected TEXT,
        mitigation TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )""")
    conn.commit()
    return conn


KNOWN_BIASES = {
    "recency_bias": "Overweighting recent events vs historical patterns",
    "confirmation_bias": "Seeking information that confirms existing beliefs",
    "availability_bias": "Overweighting easily recalled information",
    "anchoring": "Over-relying on first piece of information encountered",
    "overconfidence": "Being too certain about predictions or knowledge",
    "sunk_cost": "Continuing because of past investment rather than future value",
    "status_quo": "Preferring current state over change even when change is better",
    "plan_completion": "Finishing what was started even when better alternatives exist",
    "optimism_bias": "Overestimating probability of positive outcomes",
    "automation_bias": "Over-trusting automated systems or own automated processes",
}


def record_reflection(event_type, event_description, reasoning="", decision="",
                      outcome="", was_correct=None, confidence_before=0.5):
    """Record a reflection on a decision or event."""
    conn = get_db()
    now = datetime.now().isoformat()
    cursor = conn.execute(
        """INSERT INTO reflections
           (event_type, event_description, reasoning_used, decision_made,
            outcome, was_correct, confidence_before, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_type, event_description, reasoning, decision,
         outcome, 1 if was_correct else (0 if was_correct is not None else None),
         confidence_before, now),
    )
    ref_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return ref_id


def evaluate_outcome(reflection_id, outcome, was_correct, lesson_learned="",
                     alternative_approach="", cognitive_bias=None):
    """After seeing the outcome, evaluate whether the reasoning was correct."""
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        """UPDATE reflections
           SET outcome = ?, was_correct = ?, lesson_learned = ?,
               alternative_approach = ?, cognitive_bias = ?, confidence_after = ?
           WHERE id = ?""",
        (outcome, 1 if was_correct else 0, lesson_learned,
         alternative_approach, cognitive_bias, 0.8 if was_correct else 0.3,
         reflection_id),
    )

    if cognitive_bias:
        _record_bias(conn, cognitive_bias)

    conn.commit()
    conn.close()


def _record_bias(conn, bias_name):
    """Track cognitive bias occurrence."""
    if bias_name in KNOWN_BIASES:
        existing = conn.execute(
            "SELECT id, occurrences FROM cognitive_biases WHERE bias_name = ?",
            (bias_name,),
        ).fetchone()
        now = datetime.now().isoformat()
        if existing:
            conn.execute(
                "UPDATE cognitive_biases SET occurrences = ?, last_detected = ? WHERE id = ?",
                (existing["occurrences"] + 1, now, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO cognitive_biases (bias_name, description, occurrences, last_detected, created_at)
                   VALUES (?, ?, 1, ?, ?)""",
                (bias_name, KNOWN_BIASES[bias_name], now, now),
            )


def record_reasoning_chain(event_id, chain_steps, conclusion, validity_score=0.5):
    """Record a reasoning chain for later review."""
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO reasoning_chains (event_id, chain, conclusion, validity_score, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (event_id, json.dumps(chain_steps), conclusion, validity_score, now),
    )
    conn.commit()
    conn.close()


def get_accuracy_stats():
    """How accurate have reflections been?"""
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as cnt FROM reflections WHERE was_correct IS NOT NULL").fetchone()["cnt"]
        correct = conn.execute("SELECT COUNT(*) as cnt FROM reflections WHERE was_correct = 1").fetchone()["cnt"]
        return {
            "total_evaluated": total,
            "correct": correct,
            "accuracy": round(correct / total, 2) if total > 0 else None,
        }
    finally:
        conn.close()


def get_bias_report():
    """Report on cognitive biases detected."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM cognitive_biases ORDER BY occurrences DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_lessons_learned(limit=20):
    """Get recent lessons learned from reflections."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT event_type, event_description, lesson_learned,
                      alternative_approach, cognitive_bias, was_correct
               FROM reflections
               WHERE lesson_learned != '' AND lesson_learned IS NOT NULL
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_metacognition_summary():
    """Summary of the agent's self-awareness."""
    accuracy = get_accuracy_stats()
    biases = get_bias_report()
    lessons = get_lessons_learned(5)

    return {
        "accuracy": accuracy,
        "biases_detected": len(biases),
        "top_biases": [{"name": b["bias_name"], "count": b["occurrences"]} for b in biases[:5]],
        "recent_lessons": [{"lesson": l["lesson_learned"], "type": l["event_type"]} for l in lessons],
    }


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"

    if cmd == "summary":
        print(json.dumps(get_metacognition_summary(), indent=2))
    elif cmd == "accuracy":
        print(json.dumps(get_accuracy_stats(), indent=2))
    elif cmd == "biases":
        for b in get_bias_report():
            print(f"  {b['bias_name']}: {b['occurrences']} occurrences (last: {b['last_detected']})")
    elif cmd == "lessons":
        for l in get_lessons_learned():
            print(f"  [{l['event_type']}] {l['lesson_learned'][:80]}")
