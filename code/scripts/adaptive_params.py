#!/usr/bin/env python3
"""adaptive_params.py - Self-tune thresholds, intervals, and limits based on performance.

Instead of static configuration, the agent learns the optimal values
for its own parameters through experimentation and feedback.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
ADAPTIVE_DB = DATA_DIR / "adaptive_params.db"


def get_db():
    conn = sqlite3.connect(str(ADAPTIVE_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS parameters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        current_value REAL NOT NULL,
        default_value REAL NOT NULL,
        min_value REAL DEFAULT 0,
        max_value REAL DEFAULT 100,
        step_size REAL DEFAULT 0.1,
        category TEXT DEFAULT 'general',
        description TEXT DEFAULT '',
        adaptation_rate REAL DEFAULT 0.1,
        exploration_rate REAL DEFAULT 0.1,
        last_adapted TEXT,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS parameter_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parameter_name TEXT NOT NULL,
        old_value REAL NOT NULL,
        new_value REAL NOT NULL,
        reward REAL DEFAULT 0,
        reason TEXT DEFAULT '',
        timestamp TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS experiments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parameter_name TEXT NOT NULL,
        baseline_value REAL NOT NULL,
        test_value REAL NOT NULL,
        metric_name TEXT NOT NULL,
        baseline_metric REAL DEFAULT 0,
        test_metric REAL DEFAULT 0,
        status TEXT DEFAULT 'running',
        started_at TEXT NOT NULL,
        ended_at TEXT
    )""")
    conn.commit()
    return conn


def register_parameter(name, default_value, min_val=0, max_val=100,
                       step=0.1, category="general", description=""):
    """Register a parameter for adaptive tuning."""
    conn = get_db()
    now = datetime.now().isoformat()
    try:
        conn.execute(
            """INSERT INTO parameters (name, current_value, default_value, min_value, max_value,
               step_size, category, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, default_value, default_value, min_val, max_val, step, category, description, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()


def get_parameter(name, default=None):
    """Get current value of an adaptive parameter."""
    conn = get_db()
    try:
        row = conn.execute("SELECT current_value FROM parameters WHERE name = ?", (name,)).fetchone()
        return row["current_value"] if row else default
    finally:
        conn.close()


def adapt_parameter(name, reward, reason=""):
    """Adapt a parameter based on observed reward."""
    conn = get_db()
    now = datetime.now().isoformat()
    row = conn.execute("SELECT * FROM parameters WHERE name = ?", (name,)).fetchone()

    if not row:
        conn.close()
        return

    old_value = row["current_value"]
    adaptation_rate = row["adaptation_rate"]

    # Epsilon-greedy: occasionally explore
    import random
    if random.random() < row["exploration_rate"]:
        # Explore: random perturbation
        new_value = old_value + random.uniform(-row["step_size"], row["step_size"])
    else:
        # Exploit: move in direction of reward
        new_value = old_value + adaptation_rate * reward * row["step_size"]

    # Clamp to bounds
    new_value = max(row["min_value"], min(row["max_value"], new_value))

    # Round to reasonable precision
    if row["step_size"] < 1:
        new_value = round(new_value, 3)
    else:
        new_value = round(new_value, 1)

    conn.execute(
        "UPDATE parameters SET current_value = ?, last_adapted = ? WHERE name = ?",
        (new_value, now, name),
    )

    conn.execute(
        """INSERT INTO parameter_history (parameter_name, old_value, new_value, reward, reason, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, old_value, new_value, reward, reason, now),
    )

    conn.commit()
    conn.close()
    return {"old": old_value, "new": new_value, "reward": reward}


def start_experiment(parameter_name, test_value, metric_name):
    """Start an A/B test for a parameter value."""
    conn = get_db()
    now = datetime.now().isoformat()
    row = conn.execute("SELECT current_value FROM parameters WHERE name = ?", (parameter_name,)).fetchone()
    if not row:
        conn.close()
        return None

    cursor = conn.execute(
        """INSERT INTO experiments (parameter_name, baseline_value, test_value, metric_name, started_at)
           VALUES (?, ?, ?, ?, ?)""",
        (parameter_name, row["current_value"], test_value, metric_name, now),
    )
    exp_id = cursor.lastrowid

    # Set parameter to test value
    conn.execute("UPDATE parameters SET current_value = ? WHERE name = ?", (test_value, parameter_name))
    conn.commit()
    conn.close()
    return exp_id


def end_experiment(experiment_id, test_metric, baseline_metric=0):
    """End an experiment and record results."""
    conn = get_db()
    now = datetime.now().isoformat()
    row = conn.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
    if not row:
        conn.close()
        return

    # Determine winner
    if test_metric > baseline_metric:
        winner = "test"
        new_value = row["test_value"]
    else:
        winner = "baseline"
        new_value = row["baseline_value"]

    conn.execute(
        """UPDATE experiments
           SET test_metric = ?, baseline_metric = ?, status = ?, ended_at = ?
           WHERE id = ?""",
        (test_metric, baseline_metric, f"completed_{winner}", now, experiment_id),
    )

    # Set parameter to winning value
    conn.execute("UPDATE parameters SET current_value = ? WHERE name = ?", (new_value, row["parameter_name"]))
    conn.commit()
    conn.close()
    return {"winner": winner, "test_metric": test_metric, "baseline_metric": baseline_metric}


def get_all_parameters():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM parameters ORDER BY category, name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_parameter_history(name, limit=20):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM parameter_history WHERE parameter_name = ? ORDER BY timestamp DESC LIMIT ?",
            (name, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_active_experiments():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM experiments WHERE status = 'running'").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_adaptive_stats():
    conn = get_db()
    try:
        params = conn.execute("SELECT COUNT(*) as cnt FROM parameters").fetchone()["cnt"]
        adapted = conn.execute("SELECT COUNT(*) as cnt FROM parameters WHERE last_adapted IS NOT NULL").fetchone()["cnt"]
        experiments = conn.execute("SELECT COUNT(*) as cnt FROM experiments").fetchone()["cnt"]
        running = conn.execute("SELECT COUNT(*) as cnt FROM experiments WHERE status = 'running'").fetchone()["cnt"]
        history = conn.execute("SELECT COUNT(*) as cnt FROM parameter_history").fetchone()["cnt"]
        return {
            "total_parameters": params, "adapted": adapted,
            "total_experiments": experiments, "running_experiments": running,
            "total_adaptations": history,
        }
    finally:
        conn.close()


# Pre-register commonly tuned parameters
DEFAULT_PARAMS = [
    ("retry_count", 3, 1, 10, "resilience", "Number of retries for failed operations"),
    ("timeout_seconds", 30, 5, 300, "resilience", "Default timeout for operations"),
    ("learning_rate", 0.3, 0.01, 1.0, "learning", "How fast to adapt to feedback"),
    ("confidence_threshold", 0.5, 0.1, 0.9, "decision", "Minimum confidence to act autonomously"),
    ("max_concurrent_tasks", 5, 1, 20, "performance", "Maximum parallel tasks"),
    ("memory_retention_days", 30, 1, 365, "memory", "How long to keep memories"),
    ("mind_loop_interval", 300, 60, 3600, "performance", "Seconds between mind loop cycles"),
    ("proactive_threshold", 0.6, 0.1, 0.9, "proactive", "Threshold for proactive actions"),
]


def init_defaults():
    """Initialize default adaptive parameters."""
    for name, default, min_v, max_v, cat, desc in DEFAULT_PARAMS:
        register_parameter(name, default, min_v, max_v, category=cat, description=desc)


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        print(json.dumps(get_adaptive_stats(), indent=2))
    elif cmd == "init":
        init_defaults()
        print("Default parameters initialized")
    elif cmd == "list":
        for p in get_all_parameters():
            changed = "*" if p["last_adapted"] else " "
            print(f"  {changed} {p['name']}: {p['current_value']} (default: {p['default_value']}) [{p['category']}]")
    elif cmd == "adapt" and len(sys.argv) > 3:
        name = sys.argv[2]
        reward = float(sys.argv[3])
        result = adapt_parameter(name, reward)
        if result:
            print(f"  {name}: {result['old']} -> {result['new']} (reward: {result['reward']})")
    elif cmd == "experiments":
        for e in get_active_experiments():
            print(f"  [{e['parameter_name']}] baseline={e['baseline_value']} test={e['test_value']}")
