#!/usr/bin/env python3
"""simulation_engine.py - Dry-run decisions before committing to them.

Simulate the likely outcomes of actions before actually performing them,
reducing costly mistakes and enabling better planning.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
SIM_DB = DATA_DIR / "simulation_engine.db"


def get_db():
    conn = sqlite3.connect(str(SIM_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS simulations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        context TEXT DEFAULT '{}',
        predicted_outcome TEXT DEFAULT '',
        predicted_confidence REAL DEFAULT 0.5,
        risk_score REAL DEFAULT 0.0,
        risk_factors TEXT DEFAULT '[]',
        alternatives TEXT DEFAULT '[]',
        recommended INTEGER DEFAULT 0,
        actual_outcome TEXT DEFAULT '',
        accuracy REAL,
        created_at TEXT NOT NULL,
        executed_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS simulation_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pattern TEXT NOT NULL,
        outcome_template TEXT NOT NULL,
        risk_factors TEXT DEFAULT '[]',
        confidence REAL DEFAULT 0.5,
        occurrences INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    conn.commit()
    return conn


def simulate(action, context=None):
    """Simulate an action and predict its outcome."""
    conn = get_db()
    now = datetime.now().isoformat()

    # Check simulation rules for similar past actions
    existing_rules = conn.execute(
        "SELECT * FROM simulation_rules ORDER BY occurrences DESC LIMIT 10"
    ).fetchall()

    best_match = None
    best_score = 0
    for rule in existing_rules:
        score = _match_pattern(rule["pattern"], action)
        if score > best_score:
            best_score = score
            best_match = rule

    # Build prediction
    risk_factors = []
    predicted_outcome = "unknown"
    confidence = 0.3
    risk_score = 0.5

    if best_match and best_score > 0.5:
        predicted_outcome = best_match["outcome_template"]
        confidence = best_match["confidence"]
        risk_factors = json.loads(best_match["risk_factors"]) if best_match["risk_factors"] else []

    # Add contextual risk factors
    ctx = context or {}
    if "ssh" in action.lower() or "remote" in action.lower():
        risk_factors.append("Remote operation - harder to rollback")
    if "delete" in action.lower() or "remove" in action.lower():
        risk_factors.append("Destructive action - data loss possible")
        risk_score += 0.2
    if "restart" in action.lower():
        risk_factors.append("Service restart - brief downtime")
        risk_score += 0.1
    if "config" in action.lower() or "settings" in action.lower():
        risk_factors.append("Configuration change - may affect behavior")

    risk_score = min(1.0, risk_score)

    # Generate alternatives
    alternatives = _suggest_alternatives(action, risk_factors)

    cursor = conn.execute(
        """INSERT INTO simulations
           (action, context, predicted_outcome, predicted_confidence,
            risk_score, risk_factors, alternatives, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (action, json.dumps(ctx), predicted_outcome, confidence,
         risk_score, json.dumps(risk_factors), json.dumps(alternatives), now),
    )
    sim_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "id": sim_id,
        "predicted_outcome": predicted_outcome,
        "confidence": confidence,
        "risk_score": risk_score,
        "risk_factors": risk_factors,
        "alternatives": alternatives,
        "recommended": risk_score < 0.5 and confidence > 0.5,
    }


def record_actual_outcome(sim_id, actual_outcome, accuracy=None):
    """Record what actually happened after executing a simulated action."""
    conn = get_db()
    now = datetime.now().isoformat()

    row = conn.execute("SELECT * FROM simulations WHERE id = ?", (sim_id,)).fetchone()
    if not row:
        conn.close()
        return

    # Calculate accuracy if not provided
    if accuracy is None:
        accuracy = _calculate_accuracy(row["predicted_outcome"], actual_outcome)

    conn.execute(
        "UPDATE simulations SET actual_outcome = ?, accuracy = ?, executed_at = ? WHERE id = ?",
        (actual_outcome, accuracy, now, sim_id),
    )

    # Update simulation rules based on outcome
    _update_rules(conn, row["action"], actual_outcome, accuracy)

    conn.commit()
    conn.close()


def _match_pattern(pattern, action):
    """Simple pattern matching between a rule pattern and an action."""
    pattern_words = set(pattern.lower().split())
    action_words = set(action.lower().split())
    if not pattern_words:
        return 0
    overlap = len(pattern_words & action_words)
    return overlap / len(pattern_words)


def _suggest_alternatives(action, risk_factors):
    """Suggest safer alternatives based on risk factors."""
    alternatives = []
    if any("destructive" in rf.lower() for rf in risk_factors):
        alternatives.append("Create backup before proceeding")
        alternatives.append("Use soft-delete (archive instead of delete)")
    if any("remote" in rf.lower() for rf in risk_factors):
        alternatives.append("Test locally first if possible")
        alternatives.append("Add extra verification step")
    if any("restart" in rf.lower() for rf in risk_factors):
        alternatives.append("Use rolling restart instead of full restart")
    return alternatives


def _calculate_accuracy(predicted, actual):
    """Calculate how accurate a prediction was."""
    if not predicted or not actual:
        return 0.5
    pred_words = set(predicted.lower().split())
    act_words = set(actual.lower().split())
    if not pred_words:
        return 0.5
    overlap = len(pred_words & act_words)
    return min(1.0, overlap / max(len(pred_words), len(act_words)))


def _update_rules(conn, action, outcome, accuracy):
    """Update simulation rules based on observed outcomes."""
    now = datetime.now().isoformat()
    pattern = " ".join(action.lower().split()[:5])

    existing = conn.execute(
        "SELECT id, occurrences FROM simulation_rules WHERE pattern = ?", (pattern,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE simulation_rules SET occurrences = ? WHERE id = ?",
            (existing["occurrences"] + 1, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO simulation_rules (pattern, outcome_template, confidence, occurrences, created_at)
               VALUES (?, ?, ?, 1, ?)""",
            (pattern, outcome, accuracy, now),
        )


def get_simulation_history(limit=20):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM simulations ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_prediction_accuracy():
    """How accurate have simulations been overall?"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT accuracy FROM simulations WHERE accuracy IS NOT NULL"
        ).fetchall()
        if not rows:
            return {"total": 0, "avg_accuracy": None}
        accuracies = [r["accuracy"] for r in rows]
        return {
            "total": len(accuracies),
            "avg_accuracy": round(sum(accuracies) / len(accuracies), 3),
        }
    finally:
        conn.close()


def get_sim_stats():
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as cnt FROM simulations").fetchone()["cnt"]
        executed = conn.execute("SELECT COUNT(*) as cnt FROM simulations WHERE executed_at IS NOT NULL").fetchone()["cnt"]
        rules = conn.execute("SELECT COUNT(*) as cnt FROM simulation_rules").fetchone()["cnt"]
        accuracy = get_prediction_accuracy()
        return {
            "total_simulations": total, "executed": executed,
            "simulation_rules": rules, "accuracy": accuracy,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        print(json.dumps(get_sim_stats(), indent=2))
    elif cmd == "simulate" and len(sys.argv) > 2:
        action = " ".join(sys.argv[2:])
        result = simulate(action)
        print(json.dumps(result, indent=2))
    elif cmd == "history":
        for s in get_simulation_history():
            print(f"  [{s['risk_score']:.1f}] {s['action'][:50]} -> {s['predicted_outcome'][:40]}")
    elif cmd == "accuracy":
        print(json.dumps(get_prediction_accuracy(), indent=2))
