#!/usr/bin/env python3
"""cross_domain_model.py - Connect insights across career, homelab, health, finances.

Finds correlations and patterns that span multiple life domains,
enabling holistic decision-making rather than siloed optimization.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List
from collections import defaultdict

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"


def get_conn(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def get_cross_domain_snapshot() -> Dict:
    """Get a snapshot of all life domains."""
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "domains": {},
    }

    # Career (projects + tasks)
    try:
        conn = get_conn(DATA_DIR / "personal.db")
        rows = conn.execute(
            "SELECT name, status FROM projects WHERE status = 'active'"
        ).fetchall()
        snapshot["domains"]["career"] = {
            "active_projects": len(rows),
            "projects": [r["name"] for r in rows],
        }
        conn.close()
    except Exception:
        snapshot["domains"]["career"] = {"active_projects": 0, "projects": []}

    # Health (habits)
    try:
        conn = get_conn(DATA_DIR / "personal.db")
        rows = conn.execute(
            """SELECT h.name, COUNT(hl.id) as log_count,
                      SUM(CASE WHEN hl.done = 1 THEN 1 ELSE 0 END) as done_count
               FROM habits h
               LEFT JOIN habit_log hl ON h.id = hl.habit_id
               WHERE h.status = 'active'
               GROUP BY h.id"""
        ).fetchall()
        habits = []
        for r in rows:
            rate = (r["done_count"] or 0) / (r["log_count"] or 1)
            habits.append({
                "name": r["name"],
                "compliance_rate": round(rate, 2),
                "total_logs": r["log_count"],
            })
        snapshot["domains"]["health"] = {
            "active_habits": len(rows),
            "habits": habits,
        }
        conn.close()
    except Exception:
        snapshot["domains"]["health"] = {"active_habits": 0, "habits": []}

    # Homelab (tasks + services)
    try:
        conn = get_conn(HERMES_HOME / "kanban.db")
        rows = conn.execute(
            """SELECT status, COUNT(*) as cnt
               FROM tasks GROUP BY status"""
        ).fetchall()
        task_stats = {r["status"]: r["cnt"] for r in rows}
        total = sum(task_stats.values())
        done = task_stats.get("done", 0)
        snapshot["domains"]["homelab"] = {
            "total_tasks": total,
            "completed": done,
            "completion_rate": round(done / total, 2) if total > 0 else 1.0,
            "active": total - done - task_stats.get("cancelled", 0),
        }
        conn.close()
    except Exception:
        snapshot["domains"]["homelab"] = {"total_tasks": 0}

    # Decisions (cross-cutting)
    try:
        conn = get_conn(DATA_DIR / "decisions.db")
        rows = conn.execute(
            """SELECT domain, COUNT(*) as cnt
               FROM decisions WHERE status = 'active'
               GROUP BY domain"""
        ).fetchall()
        snapshot["domains"]["decisions"] = {
            "active_by_domain": {r["domain"]: r["cnt"] for r in rows},
            "total_active": sum(r["cnt"] for r in rows),
        }
        conn.close()
    except Exception:
        snapshot["domains"]["decisions"] = {"total_active": 0}

    # Knowledge (temporal KG)
    try:
        conn = get_conn(HERMES_HOME / "temporal_kg.db")
        rows = conn.execute(
            """SELECT type, COUNT(*) as cnt
               FROM entities GROUP BY type"""
        ).fetchall()
        snapshot["domains"]["knowledge"] = {
            "entities_by_type": {r["type"]: r["cnt"] for r in rows},
            "total_entities": sum(r["cnt"] for r in rows),
        }
        conn.close()
    except Exception:
        snapshot["domains"]["knowledge"] = {"total_entities": 0}

    return snapshot


def find_correlations() -> List[Dict]:
    """Find correlations across domains (e.g., busier at work = fewer habits done)."""
    correlations = []

    # Check if task completion correlates with habit compliance
    try:
        conn_personal = get_conn(DATA_DIR / "personal.db")
        conn_kanban = get_conn(HERMES_HOME / "kanban.db")

        # Get habit compliance by day
        habit_by_day = conn_personal.execute(
            """SELECT date, SUM(CASE WHEN done = 1 THEN 1 ELSE 0 END) as done,
                      COUNT(*) as total
               FROM habit_log
               WHERE date > ?
               GROUP BY date""",
            ((datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d"),),
        ).fetchall()

        # Get task completions by day
        task_by_day = conn_kanban.execute(
            """SELECT date(completed_at) as day, COUNT(*) as cnt
               FROM tasks
               WHERE completed_at > ? AND status = 'done'
               GROUP BY day""",
            ((datetime.now() - timedelta(days=14)).isoformat(),),
        ).fetchall()

        task_map = {r["day"]: r["cnt"] for r in task_by_day}

        for h in habit_by_day:
            day = h["date"]
            habit_rate = h["done"] / h["total"] if h["total"] > 0 else 0
            task_count = task_map.get(day, 0)

            if habit_rate < 0.5 and task_count > 5:
                correlations.append({
                    "type": "overwork_pattern",
                    "date": day,
                    "description": f"Low habit compliance ({habit_rate:.0%}) with high task load ({task_count} tasks)",
                })

        conn_personal.close()
        conn_kanban.close()
    except Exception:
        pass

    return correlations


def get_balance_score() -> Dict:
    """Calculate a balance score across life domains."""
    snapshot = get_cross_domain_snapshot()
    scores = {}

    # Career: active projects reasonable
    career = snapshot["domains"].get("career", {})
    active_projects = career.get("active_projects", 0)
    if 1 <= active_projects <= 3:
        scores["career"] = 1.0
    elif active_projects > 3:
        scores["career"] = 0.5
    else:
        scores["career"] = 0.3

    # Health: habit compliance
    health = snapshot["domains"].get("health", {})
    habits = health.get("habits", [])
    if habits:
        avg_compliance = sum(h["compliance_rate"] for h in habits) / len(habits)
        scores["health"] = avg_compliance
    else:
        scores["health"] = 0.5

    # Homelab: task completion rate + workload balance
    homelab = snapshot["domains"].get("homelab", {})
    completion = homelab.get("completion_rate", 0.5)
    active = homelab.get("active", 0)
    total = homelab.get("total_tasks", 0)
    if total == 0:
        scores["homelab"] = 1.0
    elif active > 10:
        scores["homelab"] = 0.3
    elif active > 5:
        scores["homelab"] = 0.6
    else:
        scores["homelab"] = completion

    # Decisions: not too many pending
    decisions = snapshot["domains"].get("decisions", {})
    pending = decisions.get("total_active", 0)
    if pending <= 3:
        scores["decisions"] = 1.0
    elif pending <= 7:
        scores["decisions"] = 0.7
    else:
        scores["decisions"] = 0.3

    overall = sum(scores.values()) / len(scores) if scores else 0

    return {
        "overall": round(overall, 2),
        "by_domain": {k: round(v, 2) for k, v in scores.items()},
        "recommendation": _get_balance_recommendation(scores),
    }


def _get_balance_recommendation(scores):
    """Generate recommendation based on balance scores."""
    lowest = min(scores, key=scores.get) if scores else None
    recommendations = {
        "career": "Focus on completing current projects before starting new ones",
        "health": "Prioritize habit consistency - even 5 minutes counts",
        "homelab": "Break large tasks into smaller actionable items",
        "decisions": "Decide or defer - don't let decisions linger",
    }
    if lowest and scores[lowest] < 0.5:
        return f"Focus on {lowest}: {recommendations.get(lowest, 'needs attention')}"
    return "All domains balanced - maintain current approach"


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "snapshot"

    if cmd == "snapshot":
        snapshot = get_cross_domain_snapshot()
        print(json.dumps(snapshot, indent=2))
    elif cmd == "balance":
        score = get_balance_score()
        print(json.dumps(score, indent=2))
    elif cmd == "correlations":
        corrs = find_correlations()
        for c in corrs:
            print(f"  [{c['type']}] {c['date']}: {c['description']}")
    elif cmd == "report":
        snapshot = get_cross_domain_snapshot()
        balance = get_balance_score()
        correlations = find_correlations()
        print(json.dumps({"snapshot": snapshot, "balance": balance, "correlations": correlations}, indent=2))
