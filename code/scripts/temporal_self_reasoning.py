#!/usr/bin/env python3
"""temporal_self_reasoning.py - Use history to predict and plan.

Uses historical patterns of behavior, success, and failure to make
predictions about what will happen next and plan accordingly.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"


def get_conn(db_path):
    """Get a connection with row factory."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def predict_task_outcome(task_title: str) -> Dict:
    """Predict likely outcome of a task based on historical patterns."""
    conn = get_conn(HERMES_HOME / "kanban.db")
    try:
        # Find similar past tasks
        words = task_title.lower().split()
        if not words:
            return {"prediction": "unknown", "confidence": 0}

        conditions = " OR ".join(["title LIKE ?" for _ in words[:5]])
        params = [f"%{w}%" for w in words[:5]]

        rows = conn.execute(
            f"""SELECT status, result, last_failure_error, consecutive_failures
                FROM tasks
                WHERE {conditions}
                ORDER BY created_at DESC LIMIT 20""",
            params,
        ).fetchall()

        if not rows:
            return {"prediction": "unknown", "confidence": 0}

        statuses = defaultdict(int)
        for r in rows:
            statuses[r["status"]] += 1

        total = len(rows)
        most_common = max(statuses, key=statuses.get)
        confidence = statuses[most_common] / total

        # Check for recent failures
        recent_failures = sum(
            1 for r in rows[:5]
            if r["status"] in ("failed", "error")
        )

        prediction = most_common
        if recent_failures > 2:
            prediction = "likely_failure"

        return {
            "prediction": prediction,
            "confidence": round(confidence, 2),
            "similar_tasks": total,
            "recent_failures": recent_failures,
            "outcome_distribution": dict(statuses),
        }
    finally:
        conn.close()


def predict_service_health(service_name: str) -> Dict:
    """Predict health of a service based on historical patterns."""
    conn_kg = get_conn(HERMES_HOME / "temporal_kg.db")
    try:
        rows = conn_kg.execute(
            """SELECT predicate, object, valid_at
               FROM facts f
               JOIN entities e ON f.subject_id = e.id
               WHERE e.name LIKE ?
               ORDER BY valid_at DESC LIMIT 30""",
            (f"%{service_name}%",),
        ).fetchall()

        if not rows:
            return {"status": "unknown", "confidence": 0}

        status_trend = []
        for r in rows:
            status_trend.append({
                "fact": r["predicate"],
                "value": r["object"],
                "date": r["valid_at"],
            })

        # Count status changes
        statuses = [r["object"].lower() for r in rows]
        health_counts = defaultdict(int)
        for s in statuses:
            if "healthy" in s or "running" in s or "active" in s:
                health_counts["healthy"] += 1
            elif "unhealthy" in s or "stopped" in s or "failed" in s:
                health_counts["unhealthy"] += 1
            else:
                health_counts["unknown"] += 1

        total = len(statuses)
        if total == 0:
            return {"status": "unknown", "confidence": 0}

        most_likely = max(health_counts, key=health_counts.get)
        confidence = health_counts[most_likely] / total

        return {
            "status": most_likely,
            "confidence": round(confidence, 2),
            "data_points": total,
            "distribution": dict(health_counts),
            "recent_trend": status_trend[:5],
        }
    finally:
        conn_kg.close()


def plan_next_actions(context: str = "") -> List[Dict]:
    """Based on current state, suggest what to do next."""
    suggestions = []

    # Check for stale knowledge
    conn_kg = get_conn(HERMES_HOME / "temporal_kg.db")
    try:
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        rows = conn_kg.execute(
            """SELECT COUNT(*) as cnt FROM facts WHERE valid_at < ?""",
            (cutoff,),
        ).fetchone()
        if rows and rows["cnt"] > 10:
            suggestions.append({
                "action": "knowledge_refresh",
                "priority": "high",
                "reason": f"{rows['cnt']} facts older than 7 days - consider refreshing",
            })
    finally:
        conn_kg.close()

    # Check for failed tasks
    conn_kb = get_conn(HERMES_HOME / "kanban.db")
    try:
        rows = conn_kb.execute(
            """SELECT COUNT(*) as cnt FROM tasks
               WHERE status IN ('failed', 'error')"""
        ).fetchone()
        if rows and rows["cnt"] > 0:
            suggestions.append({
                "action": "review_failures",
                "priority": "medium",
                "reason": f"{rows['cnt']} failed tasks need attention",
            })
    finally:
        conn_kb.close()

    # Check for unapplied learnings
    learning_db = DATA_DIR / "failure_learning.db"
    if learning_db.exists():
        conn_fl = get_conn(learning_db)
        try:
            rows = conn_fl.execute(
                """SELECT COUNT(*) as cnt FROM learnings WHERE applied = 0"""
            ).fetchone()
            if rows and rows["cnt"] > 0:
                suggestions.append({
                    "action": "apply_learnings",
                    "priority": "medium",
                    "reason": f"{rows['cnt']} unapplied learnings from failures",
                })
        finally:
            conn_fl.close()

    # Check for active decisions without outcomes
    decisions_db = DATA_DIR / "decisions.db"
    if decisions_db.exists():
        conn_dec = get_conn(decisions_db)
        try:
            rows = conn_dec.execute(
                """SELECT COUNT(*) as cnt FROM decisions
                   WHERE status = 'active' AND outcome = ''"""
            ).fetchone()
            if rows and rows["cnt"] > 2:
                suggestions.append({
                    "action": "resolve_decisions",
                    "priority": "low",
                    "reason": f"{rows['cnt']} active decisions without outcomes",
                })
        finally:
            conn_dec.close()

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda x: priority_order.get(x["priority"], 99))

    return suggestions


def get_self_assessment() -> Dict:
    """Generate a self-assessment of current state."""
    assessment = {
        "timestamp": datetime.now().isoformat(),
        "knowledge_freshness": "unknown",
        "task_reliability": "unknown",
        "learning_progress": "unknown",
        "areas_of_strength": [],
        "areas_for_improvement": [],
    }

    # Knowledge freshness
    conn_kg = get_conn(HERMES_HOME / "temporal_kg.db")
    try:
        rows = conn_kg.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN valid_at > ? THEN 1 ELSE 0 END) as recent
               FROM facts""",
            ((datetime.now() - timedelta(days=7)).isoformat(),),
        ).fetchone()
        if rows and rows["total"] > 0:
            ratio = (rows["recent"] or 0) / rows["total"]
            if ratio > 0.7:
                assessment["knowledge_freshness"] = "excellent"
            elif ratio > 0.4:
                assessment["knowledge_freshness"] = "good"
            elif ratio > 0.1:
                assessment["knowledge_freshness"] = "aging"
            else:
                assessment["knowledge_freshness"] = "stale"
    finally:
        conn_kg.close()

    # Task reliability
    conn_kb = get_conn(HERMES_HOME / "kanban.db")
    try:
        rows = conn_kb.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done,
                      SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
               FROM tasks"""
        ).fetchone()
        if rows and rows["total"] > 0:
            done_rate = (rows["done"] or 0) / rows["total"]
            if done_rate > 0.8:
                assessment["task_reliability"] = "excellent"
            elif done_rate > 0.6:
                assessment["task_reliability"] = "good"
            elif done_rate > 0.4:
                assessment["task_reliability"] = "needs_improvement"
            else:
                assessment["task_reliability"] = "poor"
    finally:
        conn_kb.close()

    # Learning progress
    learning_db = DATA_DIR / "failure_learning.db"
    if learning_db.exists():
        conn_fl = get_conn(learning_db)
        try:
            rows = conn_fl.execute(
                """SELECT COUNT(*) as total,
                          SUM(CASE WHEN applied = 1 THEN 1 ELSE 0 END) as applied
                   FROM learnings"""
            ).fetchone()
            if rows and rows["total"] > 0:
                applied_rate = (rows["applied"] or 0) / rows["total"]
                if applied_rate > 0.7:
                    assessment["learning_progress"] = "excellent"
                elif applied_rate > 0.3:
                    assessment["learning_progress"] = "good"
                else:
                    assessment["learning_progress"] = "needs_work"
        finally:
            conn_fl.close()

    return assessment


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "assess"

    if cmd == "assess":
        assessment = get_self_assessment()
        print(json.dumps(assessment, indent=2))

    elif cmd == "predict" and len(sys.argv) > 2:
        name = " ".join(sys.argv[2:])
        result = predict_task_outcome(name)
        print(json.dumps(result, indent=2))

    elif cmd == "plan":
        actions = plan_next_actions()
        for a in actions:
            print(f"  [{a['priority']}] {a['action']}: {a['reason']}")

    elif cmd == "service" and len(sys.argv) > 2:
        name = sys.argv[2]
        result = predict_service_health(name)
        print(json.dumps(result, indent=2))
