#!/usr/bin/env python3
"""uncertainty_engine.py - Quantify confidence in knowledge and decisions.

The agent doesn't know what it doesn't know. This module assigns confidence
scores to facts, decisions, and predictions based on source quality, recency,
corroboration, and historical accuracy.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
UNCERTAINTY_DB = DATA_DIR / "uncertainty.db"


def get_db():
    conn = sqlite3.connect(str(UNCERTAINTY_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS confidence_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        confidence REAL NOT NULL,
        factors TEXT DEFAULT '{}',
        source_count INTEGER DEFAULT 0,
        corroboration_level TEXT DEFAULT 'none',
        recency_score REAL DEFAULT 0.5,
        historical_accuracy REAL DEFAULT 0.5,
        computed_at TEXT NOT NULL,
        UNIQUE(entity_type, entity_id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS confidence_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        old_confidence REAL,
        new_confidence REAL,
        reason TEXT,
        timestamp TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS unknowns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL,
        domain TEXT DEFAULT 'general',
        priority INTEGER DEFAULT 0,
        status TEXT DEFAULT 'open',
        answered_at TEXT,
        answer TEXT,
        created_at TEXT NOT NULL
    )""")
    conn.commit()
    return conn


def compute_confidence(entity_type, entity_id, source_count=1, age_days=0,
                       corroborated=False, historical_accuracy=0.5):
    """Compute a confidence score for a piece of knowledge.

    Factors:
    - Source quality: more independent sources = higher confidence
    - Recency: newer = higher (decays over time)
    - Corroboration: multiple agreeing sources = higher
    - Historical accuracy: how often this source/type has been right
    """
    # Source score: log scale, diminishing returns
    import math
    source_score = min(1.0, math.log(max(source_count, 1) + 1) / math.log(11))

    # Recency score: exponential decay with 30-day half-life
    import math
    recency_score = math.exp(-0.023 * age_days)  # ln(2)/30 ≈ 0.023

    # Corroboration bonus
    corroboration_score = 1.0 if corroborated else 0.6

    # Weighted combination
    confidence = (
        0.30 * source_score +
        0.25 * recency_score +
        0.20 * corroboration_score +
        0.25 * historical_accuracy
    )
    confidence = max(0.0, min(1.0, confidence))

    factors = {
        "source_score": round(source_score, 3),
        "recency_score": round(recency_score, 3),
        "corroboration_score": round(corroboration_score, 3),
        "historical_accuracy": round(historical_accuracy, 3),
    }
    corroboration_level = "high" if corroborated else ("moderate" if source_count > 1 else "none")

    return {
        "confidence": round(confidence, 3),
        "factors": factors,
        "source_count": source_count,
        "corroboration_level": corroboration_level,
        "recency_score": round(recency_score, 3),
        "historical_accuracy": round(historical_accuracy, 3),
    }


def store_confidence(entity_type, entity_id, confidence_data):
    """Store computed confidence score."""
    conn = get_db()
    now = datetime.now().isoformat()

    # Get old score for history
    old = conn.execute(
        "SELECT confidence FROM confidence_scores WHERE entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
    ).fetchone()
    old_val = old["confidence"] if old else None

    conn.execute(
        """INSERT INTO confidence_scores
           (entity_type, entity_id, confidence, factors, source_count,
            corroboration_level, recency_score, historical_accuracy, computed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(entity_type, entity_id) DO UPDATE SET
           confidence = excluded.confidence, factors = excluded.factors,
           source_count = excluded.source_count,
           corroboration_level = excluded.corroboration_level,
           recency_score = excluded.recency_score,
           historical_accuracy = excluded.historical_accuracy,
           computed_at = excluded.computed_at""",
        (entity_type, entity_id, confidence_data["confidence"],
         json.dumps(confidence_data["factors"]), confidence_data["source_count"],
         confidence_data["corroboration_level"], confidence_data["recency_score"],
         confidence_data["historical_accuracy"], now),
    )

    if old_val is not None and abs(old_val - confidence_data["confidence"]) > 0.1:
        conn.execute(
            """INSERT INTO confidence_history
               (entity_type, entity_id, old_confidence, new_confidence, reason, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (entity_type, entity_id, old_val, confidence_data["confidence"],
             "automatic recomputation", now),
        )

    conn.commit()
    conn.close()


def record_unknown(question, domain="general", priority=0):
    """Record something the agent doesn't know."""
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO unknowns (question, domain, priority, status, created_at)
           VALUES (?, ?, ?, 'open', ?)""",
        (question, domain, priority, now),
    )
    conn.commit()
    conn.close()


def answer_unknown(question_id, answer):
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE unknowns SET status = 'answered', answered_at = ?, answer = ? WHERE id = ?",
        (now, answer, question_id),
    )
    conn.commit()
    conn.close()


def get_confidence_report():
    """Get confidence distribution across all scored entities."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT entity_type, AVG(confidence) as avg_conf, COUNT(*) as cnt,
                      MIN(confidence) as min_conf, MAX(confidence) as max_conf
               FROM confidence_scores GROUP BY entity_type"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_low_confidence(threshold=0.4):
    """Find knowledge with low confidence."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT entity_type, entity_id, confidence, factors, corroboration_level
               FROM confidence_scores
               WHERE confidence < ?
               ORDER BY confidence ASC""",
            (threshold,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_open_unknowns():
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT * FROM unknowns WHERE status = 'open'
               ORDER BY priority DESC, created_at ASC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_confidence_stats():
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as cnt FROM confidence_scores").fetchone()["cnt"]
        avg = conn.execute("SELECT AVG(confidence) as avg FROM confidence_scores").fetchone()["avg"]
        low = conn.execute("SELECT COUNT(*) as cnt FROM confidence_scores WHERE confidence < 0.4").fetchone()["cnt"]
        high = conn.execute("SELECT COUNT(*) as cnt FROM confidence_scores WHERE confidence > 0.8").fetchone()["cnt"]
        unknowns = conn.execute("SELECT COUNT(*) as cnt FROM unknowns WHERE status = 'open'").fetchone()["cnt"]
        return {
            "total_scored": total,
            "average_confidence": round(avg or 0, 3),
            "low_confidence": low,
            "high_confidence": high,
            "open_unknowns": unknowns,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        print(json.dumps(get_confidence_stats(), indent=2))
    elif cmd == "report":
        for r in get_confidence_report():
            print(f"  {r['entity_type']}: avg={r['avg_conf']:.2f} ({r['cnt']} items, range {r['min_conf']:.2f}-{r['max_conf']:.2f})")
    elif cmd == "low":
        for item in get_low_confidence():
            print(f"  [{item['entity_type']}] {item['entity_id']}: {item['confidence']:.2f} ({item['corroboration_level']})")
    elif cmd == "unknowns":
        for u in get_open_unknowns():
            print(f"  [{u['domain']}] {u['question']}")
