#!/usr/bin/env python3
"""failure_learning_pipeline.py - Capture failures, analyze root causes, record learnings.

Every failure gets:
1. Recorded with context (what, when, where)
2. Root cause analyzed (pattern matching against known failure classes)
3. Learning extracted (what to do differently next time)
4. Behavior updated (modify thresholds, add guards, update SOPs)
"""

import json
import sqlite3
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
LEARNING_DB = DATA_DIR / "failure_learning.db"


def get_learning_db() -> sqlite3.Connection:
    """Get or create the failure learning database."""
    conn = sqlite3.connect(str(LEARNING_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS failures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        component TEXT NOT NULL,
        failure_type TEXT NOT NULL,
        error_message TEXT,
        context TEXT,
        root_cause TEXT,
        learning TEXT,
        behavior_change TEXT,
        severity TEXT DEFAULT 'medium',
        resolved INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS failure_patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pattern_name TEXT UNIQUE NOT NULL,
        description TEXT,
        root_cause_template TEXT,
        learning_template TEXT,
        behavior_change_template TEXT,
        occurrences INTEGER DEFAULT 0,
        last_seen TEXT,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS learnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        failure_id INTEGER,
        learning_text TEXT NOT NULL,
        domain TEXT,
        applied INTEGER DEFAULT 0,
        applied_at TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (failure_id) REFERENCES failures(id)
    )""")
    conn.commit()
    return conn


KNOWN_PATTERNS = [
    {"name": "connection_timeout", "keywords": ["timeout", "timed out", "connection refused", "connection reset"],
     "root_cause": "Network or service unavailable",
     "learning": "Add retry with exponential backoff. Check service health before calling.",
     "behavior": "Add 3-retry wrapper with 2s/4s/8s backoff for external API calls."},
    {"name": "permission_denied", "keywords": ["permission denied", "access denied", "403", "forbidden"],
     "root_cause": "Insufficient permissions or wrong auth token",
     "learning": "Verify auth tokens are current. Check file permissions before write.",
     "behavior": "Add pre-flight auth check before sensitive operations."},
    {"name": "disk_full", "keywords": ["no space left", "disk full", "ENOSPC"],
     "root_cause": "Disk space exhaustion",
     "learning": "Run cleanup before large writes. Monitor disk usage proactively.",
     "behavior": "Add disk space check before log writes and cache operations."},
    {"name": "memory_pressure", "keywords": ["out of memory", "OOMKilled", "memory", "killed process"],
     "root_cause": "System memory exhaustion",
     "learning": "Reduce batch sizes. Process data in chunks. Monitor RSS.",
     "behavior": "Add memory check before loading large datasets."},
    {"name": "stale_state", "keywords": ["stale", "out of date", "expired", "superseded", "already exists"],
     "root_cause": "Race condition or stale cache",
     "learning": "Add TTL to cached state. Check freshness before acting on state.",
     "behavior": "Add timestamp-based staleness check to state reads."},
    {"name": "dependency_missing", "keywords": ["module not found", "import error", "no such file", "not found"],
     "root_cause": "Missing dependency or wrong path",
     "learning": "Check dependencies exist before importing. Add fallback imports.",
     "behavior": "Add try/except import with clear error message."},
    {"name": "rate_limit", "keywords": ["rate limit", "429", "too many requests", "throttl"],
     "root_cause": "API rate limit exceeded",
     "learning": "Add request pacing. Respect Retry-After headers.",
     "behavior": "Add rate limiter with configurable per-API limits."},
    {"name": "data_corruption", "keywords": ["corrupt", "invalid json", "parse error", "malformed"],
     "root_cause": "Data written incompletely or concurrent write",
     "learning": "Use atomic writes (tmp+rename). Validate before commit.",
     "behavior": "Enforce atomic write pattern for all state files."},
]


def record_failure(component, error_message, context="", severity="medium"):
    """Record a failure and attempt to classify it."""
    conn = get_learning_db()
    now = datetime.now().isoformat()
    error_lower = error_message.lower()

    failure_type = "unknown"
    root_cause = "Unknown - requires manual analysis"
    learning = "No automatic learning available"

    for pattern in KNOWN_PATTERNS:
        if any(kw in error_lower for kw in pattern["keywords"]):
            failure_type = pattern["name"]
            root_cause = pattern["root_cause"]
            learning = pattern["learning"]
            break

    cursor = conn.execute(
        """INSERT INTO failures (timestamp, component, failure_type, error_message,
           context, root_cause, learning, severity, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (now, component, failure_type, error_message, context, root_cause, learning, severity, now),
    )
    failure_id = cursor.lastrowid

    if learning != "No automatic learning available":
        conn.execute(
            """INSERT INTO learnings (failure_id, learning_text, domain, created_at)
               VALUES (?, ?, ?, ?)""",
            (failure_id, learning, component, now),
        )

    for pattern in KNOWN_PATTERNS:
        if any(kw in error_lower for kw in pattern["keywords"]):
            try:
                conn.execute(
                    """INSERT INTO failure_patterns (pattern_name, description, root_cause_template,
                       learning_template, behavior_change_template, occurrences, last_seen, created_at)
                       VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                    (pattern["name"], error_message, pattern["root_cause"],
                     pattern["learning"], pattern["behavior"], now, now),
                )
            except sqlite3.IntegrityError:
                conn.execute(
                    """UPDATE failure_patterns
                       SET occurrences = occurrences + 1, last_seen = ?
                       WHERE pattern_name = ?""",
                    (now, pattern["name"]),
                )
            break

    conn.commit()
    conn.close()
    return failure_id


def get_learning_stats():
    """Get statistics about the learning pipeline."""
    conn = get_learning_db()
    try:
        stats = {}
        r = conn.execute("SELECT COUNT(*) as cnt FROM failures").fetchone()
        stats["total_failures"] = r["cnt"]

        r = conn.execute("SELECT COUNT(*) as cnt FROM failures WHERE resolved = 1").fetchone()
        stats["resolved"] = r["cnt"]

        r = conn.execute("SELECT COUNT(*) as cnt FROM learnings").fetchone()
        stats["total_learnings"] = r["cnt"]

        r = conn.execute("SELECT COUNT(*) as cnt FROM learnings WHERE applied = 1").fetchone()
        stats["applied_learnings"] = r["cnt"]

        r = conn.execute("SELECT COUNT(*) as cnt FROM failure_patterns WHERE occurrences > 1").fetchone()
        stats["recurring_patterns"] = r["cnt"]

        rows = conn.execute(
            """SELECT failure_type, COUNT(*) as cnt
               FROM failures GROUP BY failure_type
               ORDER BY cnt DESC LIMIT 5"""
        ).fetchall()
        stats["top_failure_types"] = [{"type": r["failure_type"], "count": r["cnt"]} for r in rows]

        return stats
    finally:
        conn.close()


def apply_behavior_changes():
    """Check if any behavior changes should be applied based on failure patterns."""
    conn = get_learning_db()
    changes = []
    try:
        rows = conn.execute(
            """SELECT pattern_name, behavior_change_template, occurrences
               FROM failure_patterns
               WHERE occurrences >= 3 AND behavior_change_template IS NOT NULL
               ORDER BY occurrences DESC"""
        ).fetchall()
        for r in rows:
            changes.append({
                "pattern": r["pattern_name"],
                "suggested_change": r["behavior_change_template"],
                "occurrences": r["occurrences"],
            })
    finally:
        conn.close()
    return changes


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        stats = get_learning_stats()
        print(json.dumps(stats, indent=2))
    elif cmd == "record" and len(sys.argv) > 3:
        component = sys.argv[2]
        error = " ".join(sys.argv[3:])
        fid = record_failure(component, error)
        print(f"Recorded failure #{fid}")
    elif cmd == "unlearned":
        conn = get_learning_db()
        rows = conn.execute(
            """SELECT * FROM failures
               WHERE (root_cause IS NULL OR root_cause LIKE '%Unknown%')
               ORDER BY created_at DESC LIMIT 50"""
        ).fetchall()
        for f in rows:
            print(f"  [{f['failure_type']}] {f['component']}: {f['error_message'][:80]}")
        conn.close()
    elif cmd == "changes":
        changes = apply_behavior_changes()
        for c in changes:
            print(f"  Pattern: {c['pattern']} ({c['occurrences']}x)")
            print(f"    Suggested: {c['suggested_change']}")
