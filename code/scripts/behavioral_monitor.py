#!/usr/bin/env python3
"""behavioral_monitor.py - Detect drift in agent's own behavior patterns.

Monitors response quality, habit compliance, task patterns, and decision
quality over time to detect degradation before it becomes critical.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List
from collections import defaultdict

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
DRIFT_DB = DATA_DIR / "behavioral_drift.db"


def get_db():
    conn = sqlite3.connect(str(DRIFT_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS behavior_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric_name TEXT NOT NULL,
        metric_value REAL NOT NULL,
        context TEXT DEFAULT '{}',
        timestamp TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS behavior_baselines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric_name TEXT UNIQUE NOT NULL,
        baseline_value REAL NOT NULL,
        window_size INTEGER DEFAULT 30,
        upper_bound REAL,
        lower_bound REAL,
        last_updated TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS drift_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric_name TEXT NOT NULL,
        baseline_value REAL,
        current_value REAL,
        drift_direction TEXT,
        drift_magnitude REAL,
        severity TEXT DEFAULT 'info',
        acknowledged INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    conn.commit()
    return conn


def record_metric(name, value, context=None):
    """Record a behavioral metric data point."""
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO behavior_metrics (metric_name, metric_value, context, timestamp) VALUES (?, ?, ?, ?)",
        (name, value, json.dumps(context or {}), now),
    )

    # Update baseline (rolling average)
    _update_baseline(conn, name)
    conn.commit()
    conn.close()


def _update_baseline(conn, metric_name):
    """Update the rolling baseline for a metric."""
    rows = conn.execute(
        """SELECT metric_value FROM behavior_metrics
           WHERE metric_name = ?
           ORDER BY timestamp DESC LIMIT 30""",
        (metric_name,),
    ).fetchall()

    if len(rows) < 5:
        return

    values = [r["metric_value"] for r in rows]
    avg = sum(values) / len(values)
    std = (sum((v - avg) ** 2 for v in values) / len(values)) ** 0.5

    existing = conn.execute(
        "SELECT id FROM behavior_baselines WHERE metric_name = ?", (metric_name,)
    ).fetchone()

    now = datetime.now().isoformat()
    if existing:
        conn.execute(
            """UPDATE behavior_baselines
               SET baseline_value = ?, upper_bound = ?, lower_bound = ?, last_updated = ?
               WHERE id = ?""",
            (avg, avg + 2 * std, max(0, avg - 2 * std), now, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO behavior_baselines (metric_name, baseline_value, upper_bound, lower_bound, last_updated)
               VALUES (?, ?, ?, ?, ?)""",
            (metric_name, avg, avg + 2 * std, max(0, avg - 2 * std), now),
        )


def check_drift():
    """Check all metrics for drift from baselines."""
    conn = get_db()
    alerts = []

    baselines = conn.execute("SELECT * FROM behavior_baselines").fetchall()

    for bl in baselines:
        # Get recent average
        recent = conn.execute(
            """SELECT AVG(metric_value) as recent_avg
               FROM behavior_metrics
               WHERE metric_name = ? AND timestamp > ?
               ORDER BY timestamp DESC LIMIT 10""",
            (bl["metric_name"], (datetime.now() - timedelta(days=7)).isoformat()),
        ).fetchone()

        if not recent or recent["recent_avg"] is None:
            continue

        current = recent["recent_avg"]
        baseline = bl["baseline_value"]

        if baseline == 0:
            continue

        drift_pct = abs(current - baseline) / baseline

        if drift_pct > 0.3:
            severity = "critical"
        elif drift_pct > 0.2:
            severity = "warning"
        elif drift_pct > 0.1:
            severity = "info"
        else:
            continue

        direction = "up" if current > baseline else "down"

        alert = {
            "metric": bl["metric_name"],
            "baseline": round(baseline, 3),
            "current": round(current, 3),
            "drift_pct": round(drift_pct, 3),
            "direction": direction,
            "severity": severity,
        }
        alerts.append(alert)

        # Store alert
        now = datetime.now().isoformat()
        existing = conn.execute(
            "SELECT id FROM drift_alerts WHERE metric_name = ? AND acknowledged = 0",
            (bl["metric_name"],),
        ).fetchone()

        if not existing:
            conn.execute(
                """INSERT INTO drift_alerts
                   (metric_name, baseline_value, current_value, drift_direction,
                    drift_magnitude, severity, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (bl["metric_name"], baseline, current, direction, drift_pct, severity, now),
            )

    conn.commit()
    conn.close()
    return alerts


def get_active_alerts():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM drift_alerts WHERE acknowledged = 0 ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_metric_history(metric_name, days=30):
    conn = get_db()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT metric_value, timestamp FROM behavior_metrics
               WHERE metric_name = ? AND timestamp > ?
               ORDER BY timestamp ASC""",
            (metric_name, cutoff),
        ).fetchall()
        return [{"value": r["metric_value"], "timestamp": r["timestamp"]} for r in rows]
    finally:
        conn.close()


def get_behavior_summary():
    conn = get_db()
    try:
        metrics = conn.execute(
            "SELECT DISTINCT metric_name FROM behavior_metrics"
        ).fetchall()

        summary = {}
        for m in metrics:
            name = m["metric_name"]
            baseline = conn.execute(
                "SELECT baseline_value, upper_bound, lower_bound FROM behavior_baselines WHERE metric_name = ?",
                (name,),
            ).fetchone()

            recent = conn.execute(
                """SELECT AVG(metric_value) as avg_val, COUNT(*) as cnt
                   FROM behavior_metrics
                   WHERE metric_name = ? AND timestamp > ?""",
                (name, (datetime.now() - timedelta(days=7)).isoformat()),
            ).fetchone()

            summary[name] = {
                "baseline": round(baseline["baseline_value"], 3) if baseline else None,
                "recent_avg": round(recent["avg_val"], 3) if recent and recent["avg_val"] else None,
                "data_points": recent["cnt"] if recent else 0,
            }

        return summary
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"

    if cmd == "check":
        alerts = check_drift()
        if alerts:
            for a in alerts:
                print(f"  [{a['severity']}] {a['metric']}: {a['baseline']} -> {a['current']} ({a['drift_pct']:.0%} {a['direction']})")
        else:
            print("  No drift detected")
    elif cmd == "alerts":
        for a in get_active_alerts():
            print(f"  [{a['severity']}] {a['metric_name']}: {a['baseline_value']} -> {a['current_value']}")
    elif cmd == "summary":
        print(json.dumps(get_behavior_summary(), indent=2))
    elif cmd == "record" and len(sys.argv) > 3:
        name = sys.argv[2]
        value = float(sys.argv[3])
        record_metric(name, value)
        print(f"Recorded {name} = {value}")
