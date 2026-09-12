#!/usr/bin/env python3
"""memory_synthesizer.py - Cross-database pattern detection and insight generation.

Synthesizes information across all databases to find patterns, correlations,
and insights that wouldn't be visible from any single database alone.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from collections import Counter, defaultdict

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"


def get_all_connections():
    """Open connections to all databases for cross-DB queries."""
    dbs = {}
    db_files = {
        "state": HERMES_HOME / "state.db",
        "temporal_kg": HERMES_HOME / "data" / "unified_memory.db",
        "claudemem": HERMES_HOME / "claudemem.db",
        "kanban": HERMES_HOME / "kanban.db",
        "shared_facts": HERMES_HOME / "shared_facts.db",
        "decisions": DATA_DIR / "decisions.db",
        "personal": DATA_DIR / "personal.db",
        "self_model": DATA_DIR / "self_model.db",
        "failure_learning": DATA_DIR / "failure_learning.db",
    }
    for name, path in db_files.items():
        if path.exists():
            conn = sqlite3.connect(str(path))
            conn.row_factory = sqlite3.Row
            dbs[name] = conn
    return dbs


def close_all(dbs):
    for conn in dbs.values():
        conn.close()


def synthesize_recurring_issues() -> List[Dict]:
    """Find recurring issues across tasks, failures, and observations."""
    dbs = get_all_connections()
    issues = []

    try:
        # Failed tasks from kanban
        if "kanban" in dbs:
            rows = dbs["kanban"].execute(
                """SELECT title, body, last_failure_error, consecutive_failures
                   FROM tasks
                   WHERE status = 'failed' OR consecutive_failures > 2
                   ORDER BY created_at DESC LIMIT 50"""
            ).fetchall()
            for r in rows:
                issues.append({
                    "source": "kanban",
                    "type": "failed_task",
                    "title": r["title"],
                    "error": r["last_failure_error"] or "",
                    "failures": r["consecutive_failures"],
                })

        # Failure patterns
        if "failure_learning" in dbs:
            rows = dbs["failure_learning"].execute(
                """SELECT pattern_name, occurrences, last_seen
                   FROM failure_patterns
                   WHERE occurrences > 2
                   ORDER BY occurrences DESC"""
            ).fetchall()
            for r in rows:
                issues.append({
                    "source": "failure_learning",
                    "type": "recurring_pattern",
                    "pattern": r["pattern_name"],
                    "count": r["occurrences"],
                    "last_seen": r["last_seen"],
                })

        # Weak capabilities
        if "self_model" in dbs:
            rows = dbs["self_model"].execute(
                """SELECT name, success_rate, attempts
                   FROM capabilities
                   WHERE attempts >= 5 AND success_rate < 0.7
                   ORDER BY success_rate ASC"""
            ).fetchall()
            for r in rows:
                issues.append({
                    "source": "self_model",
                    "type": "weak_capability",
                    "name": r["name"],
                    "success_rate": r["success_rate"],
                    "attempts": r["attempts"],
                })

    finally:
        close_all(dbs)

    return issues


def synthesize_temporal_patterns() -> Dict:
    """Find time-based patterns across all data sources."""
    dbs = get_all_connections()
    patterns = {"hourly_activity": defaultdict(int), "daily_activity": defaultdict(int)}

    try:
        if "state" in dbs:
            rows = dbs["state"].execute(
                """SELECT started_at FROM sessions
                   WHERE started_at > ?
                   ORDER BY started_at""",
                ((datetime.now() - timedelta(days=30)).timestamp(),),
            ).fetchall()
            for r in rows:
                dt = datetime.fromtimestamp(r["started_at"])
                patterns["hourly_activity"][dt.hour] += 1
                patterns["daily_activity"][dt.strftime("%A")] += 1

        if "kanban" in dbs:
            rows = dbs["kanban"].execute(
                """SELECT created_at FROM tasks
                   WHERE created_at > ?
                   ORDER BY created_at""",
                (int((datetime.now() - timedelta(days=30)).timestamp()),),
            ).fetchall()
            for r in rows:
                dt = datetime.fromtimestamp(r["created_at"])
                patterns["hourly_activity"][dt.hour] += 1
                patterns["daily_activity"][dt.strftime("%A")] += 1

        # Peak hours
        if patterns["hourly_activity"]:
            peak_hour = max(patterns["hourly_activity"], key=patterns["hourly_activity"].get)
            patterns["peak_hour"] = f"{peak_hour}:00"

        if patterns["daily_activity"]:
            peak_day = max(patterns["daily_activity"], key=patterns["daily_activity"].get)
            patterns["peak_day"] = peak_day

    finally:
        close_all(dbs)

    return patterns


def synthesize_entity_health() -> List[Dict]:
    """Assess health of tracked entities (services, projects, etc)."""
    dbs = get_all_connections()
    entities = []

    try:
        if "temporal_kg" in dbs:
            rows = dbs["temporal_kg"].execute(
                """SELECT e.name, e.type, e.summary,
                          COUNT(f.id) as fact_count,
                          MAX(f.valid_at) as last_fact
                   FROM entities e
                   LEFT JOIN facts f ON e.id = f.subject_id
                   GROUP BY e.id
                   ORDER BY fact_count DESC"""
            ).fetchall()

            now = datetime.now()
            for r in rows:
                last_fact_dt = None
                if r["last_fact"]:
                    try:
                        last_fact_dt = datetime.fromisoformat(r["last_fact"]).replace(tzinfo=None)
                    except Exception:
                        pass

                freshness = "unknown"
                if last_fact_dt:
                    days_old = (now - last_fact_dt).days
                    if days_old < 1:
                        freshness = "fresh"
                    elif days_old < 7:
                        freshness = "recent"
                    elif days_old < 30:
                        freshness = "aging"
                    else:
                        freshness = "stale"

                entities.append({
                    "name": r["name"],
                    "type": r["type"],
                    "fact_count": r["fact_count"],
                    "last_fact": r["last_fact"],
                    "freshness": freshness,
                    "summary": r["summary"],
                })

    finally:
        close_all(dbs)

    return entities


def generate_insight_report() -> Dict:
    """Generate a comprehensive insight report combining all syntheses."""
    recurring = synthesize_recurring_issues()
    temporal = synthesize_temporal_patterns()
    entities = synthesize_entity_health()

    # Count issues by type
    issue_counts = Counter(i["type"] for i in recurring)

    # Stale entities
    stale_entities = [e for e in entities if e["freshness"] in ("stale", "aging")]

    report = {
        "generated_at": datetime.now().isoformat(),
        "recurring_issues": {
            "total": len(recurring),
            "by_type": dict(issue_counts),
            "items": recurring[:10],
        },
        "temporal_patterns": {
            "peak_hour": temporal.get("peak_hour", "unknown"),
            "peak_day": temporal.get("peak_day", "unknown"),
        },
        "entity_health": {
            "total_tracked": len(entities),
            "fresh": len([e for e in entities if e["freshness"] == "fresh"]),
            "stale": len(stale_entities),
            "stale_entities": [e["name"] for e in stale_entities[:5]],
        },
    }

    # Actionable recommendations
    recommendations = []
    if issue_counts.get("failed_task", 0) > 3:
        recommendations.append("Multiple failed tasks detected - review task execution pipeline")
    if issue_counts.get("recurring_pattern", 0) > 2:
        recommendations.append("Recurring failure patterns - consider adding preventive guards")
    if stale_entities:
        recommendations.append(f"Stale entities: {', '.join(e['name'] for e in stale_entities[:3])}")
    if issue_counts.get("weak_capability", 0) > 0:
        recommendations.append("Weak capabilities identified - focus training on these areas")

    report["recommendations"] = recommendations
    return report


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"

    if cmd == "report":
        report = generate_insight_report()
        print(json.dumps(report, indent=2, default=str))
    elif cmd == "issues":
        issues = synthesize_recurring_issues()
        for i in issues:
            print(f"  [{i['source']}] {i['type']}: {json.dumps({k:v for k,v in i.items() if k not in ('source','type')})}")
    elif cmd == "entities":
        entities = synthesize_entity_health()
        for e in entities:
            print(f"  [{e['freshness']}] {e['name']} ({e['type']}): {e['fact_count']} facts")
