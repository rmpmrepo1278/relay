#!/usr/bin/env python3
"""self_modifier.py - Evolve the agent's own prompts, thresholds, and behavior rules.

The agent should be able to modify itself based on what it learns —
adjusting thresholds, updating prompts, and tweaking behavior rules
while staying within safety bounds.
"""

import json
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
MODIFIER_DB = DATA_DIR / "self_modifier.db"


def get_db():
    conn = sqlite3.connect(str(MODIFIER_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS modifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target TEXT NOT NULL,
        modification_type TEXT NOT NULL,
        old_value TEXT NOT NULL,
        new_value TEXT NOT NULL,
        reason TEXT NOT NULL,
        confidence REAL DEFAULT 0.5,
        approved INTEGER DEFAULT 0,
        applied INTEGER DEFAULT 0,
        reverted INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        applied_at TEXT,
        reverted_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS behavior_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_name TEXT UNIQUE NOT NULL,
        rule_text TEXT NOT NULL,
        category TEXT DEFAULT 'general',
        priority INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1,
        success_count INTEGER DEFAULT 0,
        failure_count INTEGER DEFAULT 0,
        version INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS prompt_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        template TEXT NOT NULL,
        variables TEXT DEFAULT '{}',
        version INTEGER DEFAULT 1,
        performance_score REAL DEFAULT 0.5,
        uses INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS safety_bounds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parameter TEXT UNIQUE NOT NULL,
        min_value REAL NOT NULL,
        max_value REAL NOT NULL,
        current_value REAL NOT NULL,
        description TEXT DEFAULT '',
        last_modified TEXT
    )""")
    conn.commit()
    _init_safety_bounds(conn)
    return conn


def _init_safety_bounds(conn):
    """Initialize default safety bounds for self-modification."""
    defaults = [
        ("retry_count", 1, 10, 3, "Number of retries for failed operations"),
        ("timeout_seconds", 10, 300, 30, "Default timeout for operations"),
        ("confidence_threshold", 0.1, 0.9, 0.5, "Minimum confidence to act"),
        ("learning_rate", 0.01, 0.5, 0.3, "How fast to adapt to feedback"),
        ("max_concurrent_tasks", 1, 20, 5, "Maximum parallel tasks"),
        ("memory_retention_days", 1, 365, 30, "How long to keep memories"),
    ]
    for param, min_val, max_val, current, desc in defaults:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO safety_bounds
                   (parameter, min_value, max_value, current_value, description)
                   VALUES (?, ?, ?, ?, ?)""",
                (param, min_val, max_val, current, desc),
            )
        except Exception:
            pass
    conn.commit()


def propose_modification(target, modification_type, old_value, new_value, reason, confidence=0.5):
    """Propose a modification to the agent's behavior."""
    conn = get_db()
    now = datetime.now().isoformat()

    # Check safety bounds
    bounds = conn.execute("SELECT * FROM safety_bounds WHERE parameter = ?", (target,)).fetchone()
    if bounds:
        try:
            new_num = float(new_value)
            if new_num < bounds["min_value"] or new_num > bounds["max_value"]:
                conn.close()
                return {"error": f"Value {new_value} out of bounds [{bounds['min_value']}, {bounds['max_value']}]", "applied": False}
        except (ValueError, TypeError):
            pass

    cursor = conn.execute(
        """INSERT INTO modifications (target, modification_type, old_value, new_value,
           reason, confidence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (target, modification_type, str(old_value), str(new_value), reason, confidence, now),
    )
    mod_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": mod_id, "applied": False}


def approve_modification(mod_id):
    """Approve a proposed modification."""
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute("UPDATE modifications SET approved = 1 WHERE id = ?", (mod_id,))
    conn.commit()
    conn.close()


def apply_modification(mod_id):
    """Apply an approved modification."""
    conn = get_db()
    now = datetime.now().isoformat()
    row = conn.execute(
        "SELECT * FROM modifications WHERE id = ? AND approved = 1", (mod_id,)
    ).fetchone()

    if not row:
        conn.close()
        return {"error": "Not found or not approved"}

    if row["modification_type"] == "behavior_rule":
        try:
            rule = json.loads(row["new_value"])
            conn.execute(
                """INSERT OR REPLACE INTO behavior_rules
                   (rule_name, rule_text, category, priority, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (rule.get("name", row["target"]), rule.get("text", ""),
                 rule.get("category", "general"), rule.get("priority", 0), now),
            )
        except (json.JSONDecodeError, TypeError):
            pass

    elif row["modification_type"] == "safety_bound":
        try:
            bounds = json.loads(row["new_value"])
            if "current_value" in bounds:
                conn.execute(
                    "UPDATE safety_bounds SET current_value = ?, last_modified = ? WHERE parameter = ?",
                    (bounds["current_value"], now, row["target"]),
                )
        except (json.JSONDecodeError, TypeError):
            pass

    elif row["modification_type"] == "prompt_template":
        try:
            template = json.loads(row["new_value"])
            conn.execute(
                """INSERT OR REPLACE INTO prompt_templates
                   (name, template, variables, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (row["target"], template.get("text", ""),
                 json.dumps(template.get("variables", {})), now),
            )
        except (json.JSONDecodeError, TypeError):
            pass

    conn.execute(
        "UPDATE modifications SET applied = 1, applied_at = ? WHERE id = ?",
        (now, mod_id),
    )
    conn.commit()
    conn.close()
    return {"applied": True}


def revert_modification(mod_id):
    """Revert an applied modification."""
    conn = get_db()
    now = datetime.now().isoformat()
    row = conn.execute(
        "SELECT * FROM modifications WHERE id = ? AND applied = 1", (mod_id,)
    ).fetchone()

    if not row:
        conn.close()
        return {"error": "Not found or not applied"}

    if row["modification_type"] == "safety_bound":
        try:
            old = json.loads(row["old_value"])
            if "current_value" in old:
                conn.execute(
                    "UPDATE safety_bounds SET current_value = ? WHERE parameter = ?",
                    (old["current_value"], row["target"]),
                )
        except (json.JSONDecodeError, TypeError):
            pass

    conn.execute(
        "UPDATE modifications SET reverted = 1, reverted_at = ? WHERE id = ?",
        (now, mod_id),
    )
    conn.commit()
    conn.close()
    return {"reverted": True}


def get_safety_bounds():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM safety_bounds").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pending_modifications():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM modifications WHERE applied = 0 AND reverted = 0 ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_behavior_rules():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM behavior_rules WHERE enabled = 1 ORDER BY priority DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_modification_stats():
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as cnt FROM modifications").fetchone()["cnt"]
        pending = conn.execute("SELECT COUNT(*) as cnt FROM modifications WHERE applied = 0 AND reverted = 0").fetchone()["cnt"]
        applied = conn.execute("SELECT COUNT(*) as cnt FROM modifications WHERE applied = 1").fetchone()["cnt"]
        reverted = conn.execute("SELECT COUNT(*) as cnt FROM modifications WHERE reverted = 1").fetchone()["cnt"]
        rules = conn.execute("SELECT COUNT(*) as cnt FROM behavior_rules WHERE enabled = 1").fetchone()["cnt"]
        return {
            "total_proposals": total, "pending": pending,
            "applied": applied, "reverted": reverted,
            "active_rules": rules,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        print(json.dumps(get_modification_stats(), indent=2))
    elif cmd == "bounds":
        for b in get_safety_bounds():
            print(f"  {b['parameter']}: {b['current_value']} [{b['min_value']}-{b['max_value']}] - {b['description']}")
    elif cmd == "rules":
        for r in get_behavior_rules():
            print(f"  [{r['priority']}] {r['rule_name']}: {r['rule_text'][:60]}")
    elif cmd == "pending":
        for m in get_pending_modifications():
            print(f"  [{m['modification_type']}] {m['target']}: {m['old_value']} -> {m['new_value']}")
