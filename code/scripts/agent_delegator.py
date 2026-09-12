#!/usr/bin/env python3
"""agent_delegator.py - Delegate tasks to sub-agents and coordinate multi-agent work.

When a task is complex or requires specialized expertise, break it into subtasks
and delegate to appropriate sub-agents (opencode instances, n8n workflows,
or other available agents).
"""

import json
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
DELEGATOR_DB = DATA_DIR / "agent_delegation.db"


def get_db():
    conn = sqlite3.connect(str(DELEGATOR_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS delegations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_task TEXT NOT NULL,
        subtask TEXT NOT NULL,
        agent_type TEXT NOT NULL,
        agent_target TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        result TEXT DEFAULT '',
        error TEXT DEFAULT '',
        priority INTEGER DEFAULT 0,
        timeout_seconds INTEGER DEFAULT 300,
        created_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS agent_capabilities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_type TEXT NOT NULL,
        capability TEXT NOT NULL,
        reliability REAL DEFAULT 0.5,
        avg_duration REAL DEFAULT 0,
        success_count INTEGER DEFAULT 0,
        failure_count INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    conn.commit()
    return conn


AGENT_TYPES = {
    "opencode": "Local opencode CLI instance for code tasks",
    "ssh_homelab": "SSH command execution on homelab",
    "n8n_workflow": "n8n automation workflow",
    "shell": "Direct shell command execution",
}


def delegate_task(subtask, agent_type="shell", agent_target="", priority=0, timeout=300):
    """Delegate a subtask to an appropriate agent."""
    conn = get_db()
    now = datetime.now().isoformat()
    cursor = conn.execute(
        """INSERT INTO delegations (parent_task, subtask, agent_type, agent_target,
           status, priority, timeout_seconds, created_at)
           VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
        ("auto", subtask, agent_type, agent_target, priority, timeout, now),
    )
    delegation_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return delegation_id


def execute_delegation(delegation_id):
    """Execute a delegated task."""
    conn = get_db()
    row = conn.execute("SELECT * FROM delegations WHERE id = ?", (delegation_id,)).fetchone()
    if not row:
        conn.close()
        return {"error": "Delegation not found"}

    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE delegations SET status = 'running', started_at = ? WHERE id = ?",
        (now, delegation_id),
    )
    conn.commit()

    result = {"status": "error", "output": ""}

    try:
        if row["agent_type"] == "shell":
            proc = subprocess.run(
                row["subtask"], shell=True, capture_output=True, text=True,
                timeout=row["timeout_seconds"],
            )
            result = {
                "status": "success" if proc.returncode == 0 else "error",
                "output": proc.stdout + proc.stderr,
                "returncode": proc.returncode,
            }
        elif row["agent_type"] == "ssh_homelab":
            proc = subprocess.run(
                ["ssh", "homelab-cmd", row["subtask"]],
                capture_output=True, text=True, timeout=row["timeout_seconds"],
            )
            result = {
                "status": "success" if proc.returncode == 0 else "error",
                "output": proc.stdout + proc.stderr,
            }
        else:
            result = {"status": "error", "output": f"Unknown agent type: {row['agent_type']}"}

    except subprocess.TimeoutExpired:
        result = {"status": "timeout", "output": f"Timed out after {row['timeout_seconds']}s"}
    except Exception as e:
        result = {"status": "error", "output": str(e)}

    completed_at = datetime.now().isoformat()
    final_status = "completed" if result["status"] == "success" else "failed"
    conn.execute(
        """UPDATE delegations SET status = ?, result = ?, error = ?, completed_at = ?
           WHERE id = ?""",
        (final_status, result["output"], result.get("error", ""), completed_at, delegation_id),
    )

    # Update capability stats
    _update_agent_stats(conn, row["agent_type"], result["status"] == "success")

    conn.commit()
    conn.close()
    return result


def _update_agent_stats(conn, agent_type, success):
    """Update agent capability statistics."""
    row = conn.execute(
        "SELECT id, success_count, failure_count FROM agent_capabilities WHERE agent_type = ?",
        (agent_type,),
    ).fetchone()

    now = datetime.now().isoformat()
    if row:
        new_success = row["success_count"] + (1 if success else 0)
        new_failure = row["failure_count"] + (0 if success else 1)
        total = new_success + new_failure
        reliability = new_success / total if total > 0 else 0.5
        conn.execute(
            "UPDATE agent_capabilities SET success_count = ?, failure_count = ?, reliability = ? WHERE id = ?",
            (new_success, new_failure, reliability, row["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO agent_capabilities (agent_type, capability, reliability, success_count, failure_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (agent_type, agent_type, 1.0 if success else 0.0, 1 if success else 0, 0 if success else 1, now),
        )


def get_delegations(status=None):
    conn = get_db()
    try:
        if status:
            rows = conn.execute("SELECT * FROM delegations WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM delegations ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_agent_reliability():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM agent_capabilities ORDER BY reliability DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_delegation_stats():
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as cnt FROM delegations").fetchone()["cnt"]
        completed = conn.execute("SELECT COUNT(*) as cnt FROM delegations WHERE status = 'completed'").fetchone()["cnt"]
        failed = conn.execute("SELECT COUNT(*) as cnt FROM delegations WHERE status = 'failed'").fetchone()["cnt"]
        running = conn.execute("SELECT COUNT(*) as cnt FROM delegations WHERE status = 'running'").fetchone()["cnt"]
        return {
            "total": total, "completed": completed, "failed": failed, "running": running,
            "success_rate": round(completed / total, 2) if total > 0 else None,
        }
    finally:
        conn.close()


def suggest_agent(task_description):
    """Suggest the best agent type for a task."""
    desc = task_description.lower()

    if any(kw in desc for kw in ["ssh", "homelab", "docker", "systemctl", "remote"]):
        return "ssh_homelab"
    elif any(kw in desc for kw in ["code", "edit", "file", "script", "python"]):
        return "opencode"
    elif any(kw in desc for kw in ["workflow", "automate", "trigger", "webhook"]):
        return "n8n_workflow"
    else:
        return "shell"


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        print(json.dumps(get_delegation_stats(), indent=2))
    elif cmd == "reliability":
        for a in get_agent_reliability():
            total = a["success_count"] + a["failure_count"]
            print(f"  {a['agent_type']}: {a['reliability']:.0%} ({a['success_count']}/{total})")
    elif cmd == "suggest" and len(sys.argv) > 2:
        task = " ".join(sys.argv[2:])
        print(f"  Suggested agent: {suggest_agent(task)}")
    elif cmd == "pending":
        for d in get_delegations("pending"):
            print(f"  [{d['agent_type']}] {d['subtask'][:60]}")
