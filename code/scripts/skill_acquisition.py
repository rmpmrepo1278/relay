#!/usr/bin/env python3
"""skill_acquisition.py - Learn new capabilities from successful task executions.

When the agent successfully completes a task, extract the steps into a reusable
SOP. Track which skills exist, which are used, and which need updating.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
SKILL_DB = DATA_DIR / "skill_acquisition.db"


def get_db():
    conn = sqlite3.connect(str(SKILL_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT DEFAULT '',
        domain TEXT DEFAULT 'general',
        steps TEXT DEFAULT '[]',
        triggers TEXT DEFAULT '[]',
        success_count INTEGER DEFAULT 0,
        failure_count INTEGER DEFAULT 0,
        avg_duration REAL DEFAULT 0,
        last_used TEXT,
        version INTEGER DEFAULT 1,
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS skill_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        skill_id INTEGER NOT NULL,
        task_id TEXT,
        success INTEGER NOT NULL,
        duration_seconds REAL,
        context TEXT DEFAULT '{}',
        error TEXT,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (skill_id) REFERENCES skills(id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS skill_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        skill_id INTEGER,
        template_type TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (skill_id) REFERENCES skills(id)
    )""")
    conn.commit()
    return conn


def create_skill(name, description="", domain="general", steps=None, triggers=None):
    """Create a new skill from observed successful execution."""
    conn = get_db()
    now = datetime.now().isoformat()
    try:
        cursor = conn.execute(
            """INSERT INTO skills (name, description, domain, steps, triggers, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, description, domain,
             json.dumps(steps or []), json.dumps(triggers or []), now, now),
        )
        skill_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return skill_id
    except sqlite3.IntegrityError:
        conn.close()
        return None


def extract_skill_from_execution(task_id, task_title, steps_taken, success=True, duration=0):
    """Given a successful execution, extract a reusable skill."""
    if not steps_taken:
        return None

    # Generate skill name from task title
    name = task_title.lower().replace(" ", "_")[:50]

    conn = get_db()
    now = datetime.now().isoformat()

    existing = conn.execute("SELECT id FROM skills WHERE name = ?", (name,)).fetchone()
    if existing:
        # Update existing skill
        skill_id = existing["id"]
        conn.execute(
            "UPDATE skills SET success_count = success_count + 1, last_used = ?, updated_at = ? WHERE id = ?",
            (now, now, skill_id),
        )
    else:
        cursor = conn.execute(
            """INSERT INTO skills (name, description, steps, triggers, success_count, last_used, created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
            (name, task_title, json.dumps(steps_taken), json.dumps([task_title.lower()]), now, now, now),
        )
        skill_id = cursor.lastrowid

    # Log usage
    conn.execute(
        """INSERT INTO skill_usage (skill_id, task_id, success, duration_seconds, timestamp)
           VALUES (?, ?, ?, ?, ?)""",
        (skill_id, task_id, 1 if success else 0, duration, now),
    )

    conn.commit()
    conn.close()
    return skill_id


def get_skill(skill_name):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM skills WHERE name = ?", (skill_name,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_skills():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM skills WHERE status = 'active' ORDER BY success_count DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def match_skill_to_task(task_description):
    """Find the best skill for a given task description."""
    skills = get_all_skills()
    task_lower = task_description.lower()

    best_match = None
    best_score = 0

    for skill in skills:
        triggers = json.loads(skill["triggers"]) if skill["triggers"] else []
        score = 0

        # Check trigger words
        for trigger in triggers:
            if trigger.lower() in task_lower:
                score += 2

        # Check name similarity
        name_words = skill["name"].lower().replace("_", " ").split()
        for word in name_words:
            if word in task_lower:
                score += 1

        # Bonus for high success rate
        total = skill["success_count"] + skill["failure_count"]
        if total > 0:
            success_rate = skill["success_count"] / total
            score *= success_rate

        if score > best_score:
            best_score = score
            best_match = skill

    if best_match and best_score > 0:
        return {
            "skill": dict(best_match),
            "score": best_score,
            "steps": json.loads(best_match["steps"]) if best_match["steps"] else [],
        }
    return None


def get_skill_stats():
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as cnt FROM skills").fetchone()["cnt"]
        active = conn.execute("SELECT COUNT(*) as cnt FROM skills WHERE status = 'active'").fetchone()["cnt"]

        # Usage stats
        total_uses = conn.execute("SELECT COUNT(*) as cnt FROM skill_usage").fetchone()["cnt"]
        successful = conn.execute("SELECT COUNT(*) as cnt FROM skill_usage WHERE success = 1").fetchone()["cnt"]

        return {
            "total_skills": total,
            "active_skills": active,
            "total_uses": total_uses,
            "success_rate": round(successful / total_uses, 2) if total_uses > 0 else None,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        print(json.dumps(get_skill_stats(), indent=2))
    elif cmd == "list":
        for s in get_all_skills():
            total = s["success_count"] + s["failure_count"]
            rate = s["success_count"] / total if total > 0 else 0
            print(f"  {s['name']}: {rate:.0%} ({s['success_count']} uses) [{s['domain']}]")
    elif cmd == "match" and len(sys.argv) > 2:
        task = " ".join(sys.argv[2:])
        result = match_skill_to_task(task)
        if result:
            print(f"  Matched: {result['skill']['name']} (score: {result['score']})")
            print(f"  Steps: {result['steps']}")
        else:
            print("  No matching skill found")
