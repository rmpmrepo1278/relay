#!/usr/bin/env python3
"""goal_engine.py - Goal-directed decomposition, tracking, and autonomous pursuit.

Turns high-level goals into decomposed subgoals, tracks progress,
and autonomously pursues unfinished goals.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
GOAL_DB = DATA_DIR / "goal_engine.db"


def get_db():
    conn = sqlite3.connect(str(GOAL_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        domain TEXT DEFAULT 'general',
        priority INTEGER DEFAULT 0,
        status TEXT DEFAULT 'active',
        progress REAL DEFAULT 0.0,
        parent_id INTEGER,
        depth INTEGER DEFAULT 0,
        deadline TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT,
        FOREIGN KEY (parent_id) REFERENCES goals(id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS goal_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        goal_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        detail TEXT,
        progress_delta REAL DEFAULT 0,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (goal_id) REFERENCES goals(id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS goal_dependencies (
        goal_id INTEGER NOT NULL,
        depends_on INTEGER NOT NULL,
        PRIMARY KEY (goal_id, depends_on),
        FOREIGN KEY (goal_id) REFERENCES goals(id),
        FOREIGN KEY (depends_on) REFERENCES goals(id)
    )""")
    conn.commit()
    return conn


def create_goal(title, description="", domain="general", priority=0, deadline=None, parent_id=None):
    conn = get_db()
    now = datetime.now().isoformat()
    depth = 0
    if parent_id:
        parent = conn.execute("SELECT depth FROM goals WHERE id = ?", (parent_id,)).fetchone()
        if parent:
            depth = parent["depth"] + 1

    cursor = conn.execute(
        """INSERT INTO goals (title, description, domain, priority, status, progress,
           parent_id, depth, deadline, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'active', 0.0, ?, ?, ?, ?, ?)""",
        (title, description, domain, priority, parent_id, depth, deadline, now, now),
    )
    goal_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO goal_log (goal_id, action, detail, timestamp) VALUES (?, 'created', ?, ?)",
        (goal_id, description, now),
    )
    conn.commit()
    conn.close()
    return goal_id


def decompose_goal(goal_id, subtasks):
    """Break a goal into sub-goals."""
    conn = get_db()
    now = datetime.now().isoformat()
    parent = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if not parent:
        conn.close()
        return []

    created = []
    for subtask in subtasks:
        cursor = conn.execute(
            """INSERT INTO goals (title, description, domain, priority, status, progress,
               parent_id, depth, deadline, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'active', 0.0, ?, ?, ?, ?, ?)""",
            (subtask.get("title", ""), subtask.get("description", ""),
             parent["domain"], subtask.get("priority", parent["priority"]),
             goal_id, parent["depth"] + 1, subtask.get("deadline", parent["deadline"]),
             now, now),
        )
        created.append(cursor.lastrowid)

    # Update parent progress based on children
    _update_parent_progress(conn, goal_id)
    conn.commit()
    conn.close()
    return created


def update_progress(goal_id, progress, detail=""):
    """Update goal progress (0.0 to 1.0)."""
    conn = get_db()
    now = datetime.now().isoformat()
    progress = max(0.0, min(1.0, progress))
    status = "completed" if progress >= 1.0 else "active"
    completed_at = now if progress >= 1.0 else None

    conn.execute(
        "UPDATE goals SET progress = ?, status = ?, updated_at = ?, completed_at = ? WHERE id = ?",
        (progress, status, now, completed_at, goal_id),
    )
    conn.execute(
        """INSERT INTO goal_log (goal_id, action, detail, progress_delta, timestamp)
           VALUES (?, 'progress', ?, ?, ?)""",
        (goal_id, detail, progress, now),
    )

    # Cascade up to parent
    row = conn.execute("SELECT parent_id FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if row and row["parent_id"]:
        _update_parent_progress(conn, row["parent_id"])

    conn.commit()
    conn.close()


def _update_parent_progress(conn, parent_id):
    """Recalculate parent progress from children."""
    children = conn.execute(
        "SELECT progress FROM goals WHERE parent_id = ?", (parent_id,)
    ).fetchall()
    if children:
        avg = sum(c["progress"] for c in children) / len(children)
        conn.execute(
            "UPDATE goals SET progress = ?, updated_at = ? WHERE id = ?",
            (avg, datetime.now().isoformat(), parent_id),
        )
        if avg >= 1.0:
            conn.execute(
                "UPDATE goals SET status = 'completed', completed_at = ? WHERE id = ?",
                (datetime.now().isoformat(), parent_id),
            )


def add_dependency(goal_id, depends_on):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO goal_dependencies (goal_id, depends_on) VALUES (?, ?)",
            (goal_id, depends_on),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()


def get_active_goals():
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT * FROM goals WHERE status = 'active'
               ORDER BY priority DESC, depth ASC, created_at ASC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_goal_tree(goal_id):
    """Get a goal and all its children as a tree."""
    conn = get_db()
    try:
        goal = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if not goal:
            return None

        result = dict(goal)
        children = conn.execute(
            "SELECT id FROM goals WHERE parent_id = ? ORDER BY priority DESC", (goal_id,)
        ).fetchall()
        result["children"] = [get_goal_tree(c["id"]) for c in children]
        return result
    finally:
        conn.close()


def get_next_actionable():
    """Find the next goal to work on (no unmet dependencies, lowest depth first)."""
    conn = get_db()
    try:
        active = conn.execute(
            """SELECT g.* FROM goals g
               WHERE g.status = 'active'
               AND g.id NOT IN (
                   SELECT gd.goal_id FROM goal_dependencies gd
                   JOIN goals dep ON gd.depends_on = dep.id
                   WHERE dep.status != 'completed'
               )
               ORDER BY g.depth ASC, g.priority DESC, g.created_at ASC
               LIMIT 1"""
        ).fetchone()
        return dict(active) if active else None
    finally:
        conn.close()


def get_goal_stats():
    conn = get_db()
    try:
        stats = {}
        for status in ["active", "completed", "paused"]:
            r = conn.execute("SELECT COUNT(*) as cnt FROM goals WHERE status = ?", (status,)).fetchone()
            stats[status] = r["cnt"]

        # Depth distribution
        rows = conn.execute("SELECT depth, COUNT(*) as cnt FROM goals GROUP BY depth").fetchall()
        stats["by_depth"] = {r["depth"]: r["cnt"] for r in rows}

        # Average progress
        r = conn.execute("SELECT AVG(progress) as avg_prog FROM goals WHERE status = 'active'").fetchone()
        stats["avg_progress"] = round(r["avg_prog"] or 0, 2)

        return stats
    finally:
        conn.close()


def suggest_next_steps():
    """Suggest what to do next based on goal state."""
    suggestions = []
    next_goal = get_next_actionable()
    if next_goal:
        suggestions.append({
            "action": "pursue_goal",
            "goal_id": next_goal["id"],
            "title": next_goal["title"],
            "progress": next_goal["progress"],
            "domain": next_goal["domain"],
        })

    # Find stalled goals (no progress update in 7+ days)
    conn = get_db()
    try:
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        rows = conn.execute(
            """SELECT id, title, progress, updated_at
               FROM goals WHERE status = 'active' AND updated_at < ?
               ORDER BY updated_at ASC""",
            (cutoff,),
        ).fetchall()
        for r in rows:
            suggestions.append({
                "action": "revive_stalled",
                "goal_id": r["id"],
                "title": r["title"],
                "stalled_since": r["updated_at"],
            })
    finally:
        conn.close()

    return suggestions


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        print(json.dumps(get_goal_stats(), indent=2))
    elif cmd == "active":
        for g in get_active_goals():
            print(f"  [{'P' + str(g['priority'])}] {g['title']} ({g['progress']:.0%}) [{g['domain']}]")
    elif cmd == "next":
        n = get_next_actionable()
        if n:
            print(f"  Next: {n['title']} (progress: {n['progress']:.0%})")
        else:
            print("  No actionable goals")
    elif cmd == "suggest":
        for s in suggest_next_steps():
            print(f"  {s['action']}: {s.get('title', '')}")
