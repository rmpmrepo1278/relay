#!/usr/bin/env python3
"""adversarial_tester.py - Challenge the agent's own assumptions and knowledge.

The agent should ask itself: "Am I sure about this? What's the counter-evidence?
What if I'm wrong? What's the strongest argument against my position?"
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
ADVERSARIAL_DB = DATA_DIR / "adversarial_testing.db"


def get_db():
    conn = sqlite3.connect(str(ADVERSARIAL_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS assumptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        claim TEXT NOT NULL,
        confidence REAL DEFAULT 0.8,
        evidence_for TEXT DEFAULT '[]',
        evidence_against TEXT DEFAULT '[]',
        counterarguments TEXT DEFAULT '[]',
        status TEXT DEFAULT 'untested',
        challenge_result TEXT,
        final_confidence REAL,
        created_at TEXT NOT NULL,
        tested_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS stress_tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assumption_id INTEGER,
        test_type TEXT NOT NULL,
        test_description TEXT NOT NULL,
        result TEXT,
        passed INTEGER,
        severity TEXT DEFAULT 'low',
        created_at TEXT NOT NULL,
        FOREIGN KEY (assumption_id) REFERENCES assumptions(id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS red_team_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        challenge TEXT NOT NULL,
        original_belief TEXT,
        revised_belief TEXT,
        confidence_change REAL,
        timestamp TEXT NOT NULL
    )""")
    conn.commit()
    return conn


def register_assumption(claim, confidence=0.8, evidence_for=None, evidence_against=None):
    """Register an assumption to be stress-tested."""
    conn = get_db()
    now = datetime.now().isoformat()
    cursor = conn.execute(
        """INSERT INTO assumptions (claim, confidence, evidence_for, evidence_against, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (claim, confidence, json.dumps(evidence_for or []), json.dumps(evidence_against or []), now),
    )
    assumption_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return assumption_id


def challenge_assumption(assumption_id, counterarguments=None, evidence_against=None):
    """Apply adversarial challenge to an assumption."""
    conn = get_db()
    now = datetime.now().isoformat()

    row = conn.execute("SELECT * FROM assumptions WHERE id = ?", (assumption_id,)).fetchone()
    if not row:
        conn.close()
        return None

    existing_against = json.loads(row["evidence_against"]) if row["evidence_against"] else []
    new_against = existing_against + (evidence_against or [])

    existing_counter = json.loads(row["counterarguments"]) if row["counterarguments"] else []
    new_counter = existing_counter + (counterarguments or [])

    # Confidence adjustment based on counter-evidence
    confidence = row["confidence"]
    if new_against:
        penalty = min(0.3, len(new_against) * 0.05)
        confidence = max(0.1, confidence - penalty)

    conn.execute(
        """UPDATE assumptions
           SET evidence_against = ?, counterarguments = ?,
               final_confidence = ?, status = 'challenged', tested_at = ?
           WHERE id = ?""",
        (json.dumps(new_against), json.dumps(new_counter), confidence, now, assumption_id),
    )

    # Log the challenge
    for arg in counterarguments or []:
        conn.execute(
            """INSERT INTO red_team_log (category, challenge, original_belief, confidence_change, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            ("counterargument", arg, row["claim"], confidence - row["confidence"], now),
        )

    conn.commit()
    conn.close()
    return {"new_confidence": confidence, "counterarguments_added": len(counterarguments or [])}


def stress_test_assumption(assumption_id):
    """Apply standard stress tests to an assumption."""
    conn = get_db()
    now = datetime.now().isoformat()

    tests = [
        ("source_quality", "Is the source of this claim reliable and first-hand?"),
        ("age_relevance", "Is this claim still relevant given how much time has passed?"),
        ("corroboration", "Is this claim corroborated by multiple independent sources?"),
        ("edge_cases", "Does this claim hold in edge cases or unusual conditions?"),
        ("causal_chain", "Is the causal reasoning behind this claim valid?"),
        ("alternative_explanation", "Could the evidence support a different conclusion?"),
        ("scope_limits", "Does this claim overgeneralize from limited data?"),
    ]

    results = []
    passed_count = 0

    for test_type, description in tests:
        # Simple heuristic scoring (in production, this could call an LLM)
        passed = True  # Assume pass unless evidence suggests otherwise
        severity = "low"

        row = conn.execute("SELECT * FROM assumptions WHERE id = ?", (assumption_id,)).fetchone()
        if row:
            evidence_count = len(json.loads(row["evidence_for"] or "[]"))
            counter_count = len(json.loads(row["evidence_against"] or "[]"))

            if test_type == "corroboration" and evidence_count < 2:
                passed = False
                severity = "high"
            elif test_type == "alternative_explanation" and counter_count > 0:
                severity = "medium"
            elif test_type == "source_quality" and evidence_count == 0:
                passed = False
                severity = "medium"

        result = "pass" if passed else "fail"
        if passed:
            passed_count += 1

        conn.execute(
            """INSERT INTO stress_tests
               (assumption_id, test_type, test_description, result, passed, severity, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (assumption_id, test_type, description, result, 1 if passed else 0, severity, now),
        )
        results.append({"test": test_type, "result": result, "severity": severity})

    # Update status
    overall = "validated" if passed_count == len(tests) else "weakened"
    conn.execute(
        "UPDATE assumptions SET status = ? WHERE id = ?",
        (overall, assumption_id),
    )
    conn.commit()
    conn.close()

    return {"tests_run": len(tests), "passed": passed_count, "overall": overall, "results": results}


def get_untested_assumptions():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM assumptions WHERE status = 'untested' ORDER BY confidence DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_weakened_assumptions():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM assumptions WHERE status = 'weakened' OR final_confidence < 0.5 ORDER BY final_confidence ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_red_team_log(limit=20):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM red_team_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_testing_stats():
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as cnt FROM assumptions").fetchone()["cnt"]
        untested = conn.execute("SELECT COUNT(*) as cnt FROM assumptions WHERE status = 'untested'").fetchone()["cnt"]
        challenged = conn.execute("SELECT COUNT(*) as cnt FROM assumptions WHERE status = 'challenged'").fetchone()["cnt"]
        weakened = conn.execute("SELECT COUNT(*) as cnt FROM assumptions WHERE status = 'weakened'").fetchone()["cnt"]
        validated = conn.execute("SELECT COUNT(*) as cnt FROM assumptions WHERE status = 'validated'").fetchone()["cnt"]
        tests = conn.execute("SELECT COUNT(*) as cnt FROM stress_tests").fetchone()["cnt"]
        test_pass = conn.execute("SELECT COUNT(*) as cnt FROM stress_tests WHERE passed = 1").fetchone()["cnt"]
        return {
            "total_assumptions": total,
            "untested": untested, "challenged": challenged,
            "weakened": weakened, "validated": validated,
            "total_tests": tests,
            "test_pass_rate": round(test_pass / tests, 2) if tests > 0 else None,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        print(json.dumps(get_testing_stats(), indent=2))
    elif cmd == "untested":
        for a in get_untested_assumptions():
            print(f"  [{a['confidence']:.2f}] {a['claim'][:80]}")
    elif cmd == "weakened":
        for a in get_weakened_assumptions():
            print(f"  [{a.get('final_confidence', a['confidence']):.2f}] {a['claim'][:80]}")
    elif cmd == "log":
        for entry in get_red_team_log():
            print(f"  [{entry['category']}] {entry['challenge'][:80]}")
