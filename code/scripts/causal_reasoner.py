#!/usr/bin/env python3
"""causal_reasoner.py - Reason about cause-and-effect, not just correlation.

Goes beyond "X and Y happen together" to "X causes Y because...",
tracking causal chains, interventions, and counterfactuals.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
CAUSAL_DB = DATA_DIR / "causal_reasoning.db"


def get_db():
    conn = sqlite3.connect(str(CAUSAL_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS causal_chains (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cause TEXT NOT NULL,
        effect TEXT NOT NULL,
        mechanism TEXT DEFAULT '',
        confidence REAL DEFAULT 0.5,
        evidence_count INTEGER DEFAULT 0,
        contradicted_by INTEGER DEFAULT 0,
        domain TEXT DEFAULT 'general',
        strength TEXT DEFAULT 'weak',
        created_at TEXT NOT NULL,
        last_validated TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS interventions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        expected_effect TEXT NOT NULL,
        actual_effect TEXT DEFAULT '',
        success INTEGER,
        context TEXT DEFAULT '{}',
        timestamp TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS counterfactuals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scenario TEXT NOT NULL,
        what_if TEXT NOT NULL,
        predicted_outcome TEXT NOT NULL,
        actual_outcome TEXT DEFAULT '',
        confidence REAL DEFAULT 0.5,
        created_at TEXT NOT NULL,
        validated_at TEXT
    )""")
    conn.commit()
    return conn


def record_causal_link(cause, effect, mechanism="", confidence=0.5, domain="general"):
    """Record a cause-and-effect relationship."""
    conn = get_db()
    now = datetime.now().isoformat()

    existing = conn.execute(
        "SELECT id, evidence_count, confidence FROM causal_chains WHERE cause = ? AND effect = ?",
        (cause, effect),
    ).fetchone()

    if existing:
        new_count = existing["evidence_count"] + 1
        new_conf = min(1.0, existing["confidence"] + 0.05)
        strength = "strong" if new_conf > 0.8 else ("moderate" if new_conf > 0.5 else "weak")
        conn.execute(
            """UPDATE causal_chains
               SET evidence_count = ?, confidence = ?, strength = ?, last_validated = ?
               WHERE id = ?""",
            (new_count, new_conf, strength, now, existing["id"]),
        )
    else:
        strength = "strong" if confidence > 0.8 else ("moderate" if confidence > 0.5 else "weak")
        conn.execute(
            """INSERT INTO causal_chains (cause, effect, mechanism, confidence, evidence_count, domain, strength, created_at, last_validated)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)""",
            (cause, effect, mechanism, confidence, domain, strength, now, now),
        )

    conn.commit()
    conn.close()


def record_intervention(action, expected_effect, actual_effect="", success=None):
    """Record an intervention and its outcome."""
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO interventions (action, expected_effect, actual_effect, success, timestamp)
           VALUES (?, ?, ?, ?, ?)""",
        (action, expected_effect, actual_effect, 1 if success else (0 if success is not None else None), now),
    )
    conn.commit()
    conn.close()


def record_counterfactual(scenario, what_if, predicted_outcome, confidence=0.5):
    """Record a what-if analysis."""
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO counterfactuals (scenario, what_if, predicted_outcome, confidence, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (scenario, what_if, predicted_outcome, confidence, now),
    )
    conn.commit()
    conn.close()


def find_causes(effect_query):
    """Find what causes a given effect."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT cause, mechanism, confidence, evidence_count, strength
               FROM causal_chains
               WHERE effect LIKE ?
               ORDER BY confidence DESC""",
            (f"%{effect_query}%",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def find_effects(cause_query):
    """Find what effects a given cause produces."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT effect, mechanism, confidence, evidence_count, strength
               FROM causal_chains
               WHERE cause LIKE ?
               ORDER BY confidence DESC""",
            (f"%{cause_query}%",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_causal_chains():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM causal_chains ORDER BY confidence DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_intervention_stats():
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as cnt FROM interventions").fetchone()["cnt"]
        success = conn.execute("SELECT COUNT(*) as cnt FROM interventions WHERE success = 1").fetchone()["cnt"]
        return {
            "total": total, "successful": success,
            "success_rate": round(success / total, 2) if total > 0 else None,
        }
    finally:
        conn.close()


def get_causal_stats():
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as cnt FROM causal_chains").fetchone()["cnt"]
        strong = conn.execute("SELECT COUNT(*) as cnt FROM causal_chains WHERE strength = 'strong'").fetchone()["cnt"]
        moderate = conn.execute("SELECT COUNT(*) as cnt FROM causal_chains WHERE strength = 'moderate'").fetchone()["cnt"]
        weak = conn.execute("SELECT COUNT(*) as cnt FROM causal_chains WHERE strength = 'weak'").fetchone()["cnt"]
        interventions = get_intervention_stats()
        counterfactuals = conn.execute("SELECT COUNT(*) as cnt FROM counterfactuals").fetchone()["cnt"]
        return {
            "causal_chains": total, "strong": strong, "moderate": moderate, "weak": weak,
            "interventions": interventions,
            "counterfactuals": counterfactuals,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        print(json.dumps(get_causal_stats(), indent=2))
    elif cmd == "chains":
        for c in get_causal_chains():
            print(f"  [{c['strength']}] {c['cause']} -> {c['effect']} ({c['confidence']:.2f})")
    elif cmd == "causes" and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        for c in find_causes(query):
            print(f"  {c['cause']} ({c['strength']}, {c['confidence']:.2f})")
    elif cmd == "effects" and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        for e in find_effects(query):
            print(f"  -> {e['effect']} ({e['strength']}, {e['confidence']:.2f})")
