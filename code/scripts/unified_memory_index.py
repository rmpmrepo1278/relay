#!/usr/bin/env python3
"""unified_memory_index.py - Cross-database query layer for Hermes.

Queries across all 8 SQLite databases to provide a unified view of Hermes knowledge.
No data movement - just cross-database joins via ATTACH DATABASE.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"

DB_PATHS = {
    "state": HERMES_HOME / "state.db",
    "memory": DATA_DIR / "unified_memory.db",
    "temporal_kg": HERMES_HOME / "temporal_kg.db",
    "claudemem": HERMES_HOME / "claudemem.db",
    "kanban": HERMES_HOME / "kanban.db",
    "shared_facts": HERMES_HOME / "shared_facts.db",
    "decisions": DATA_DIR / "decisions.db",
    "personal": DATA_DIR / "personal.db",
}


def get_unified_conn() -> sqlite3.Connection:
    """Open state.db as primary and ATTACH all other databases."""
    conn = sqlite3.connect(str(DB_PATHS["state"]))
    conn.row_factory = sqlite3.Row

    alias_map = {
        "memory": "unified_memory",
        "temporal_kg": "tkg",
        "claudemem": "cmem",
        "kanban": "kanban",
        "shared_facts": "sfacts",
        "decisions": "decisions",
        "personal": "personal",
    }

    for alias, path in DB_PATHS.items():
        if alias == "state":
            continue
        if path.exists():
            try:
                conn.execute(f"ATTACH DATABASE ? AS ?", (str(path), alias_map[alias]))
            except Exception:
                pass

    return conn


def search_all(query: str, limit: int = 20) -> List[Dict]:
    """Full-text search across all databases that have FTS."""
    conn = get_unified_conn()
    results = []

    try:
        # Search unified_memory memory_store
        try:
            rows = conn.execute(
                """SELECT key, value, domain, source, created_at
                   FROM unified_memory.memory_store
                   WHERE memory_store MATCH ? LIMIT ?""",
                (query, limit),
            ).fetchall()
            for r in rows:
                results.append({
                    "source": "memory_store",
                    "key": r["key"],
                    "content": r["value"],
                    "domain": r["domain"],
                    "created_at": r["created_at"],
                })
        except Exception:
            pass

        # Search claudemem observations
        try:
            rows = conn.execute(
                """SELECT id, content, source, timestamp
                   FROM cmem.observations
                   WHERE observations MATCH ? LIMIT ?""",
                (query, limit),
            ).fetchall()
            for r in rows:
                results.append({
                    "source": "claudemem",
                    "key": r["id"],
                    "content": r["content"],
                    "domain": r["source"],
                    "created_at": datetime.fromtimestamp(r["timestamp"]).isoformat(),
                })
        except Exception:
            pass

        # Search shared_facts
        try:
            rows = conn.execute(
                """SELECT fact, category, source, created_at
                   FROM sfacts.shared_facts
                   WHERE shared_facts MATCH ? LIMIT ?""",
                (query, limit),
            ).fetchall()
            for r in rows:
                results.append({
                    "source": "shared_facts",
                    "key": r["fact"][:80],
                    "content": r["fact"],
                    "domain": r["category"],
                    "created_at": r["created_at"],
                })
        except Exception:
            pass

        # Search temporal_kg facts
        try:
            rows = conn.execute(
                """SELECT f.predicate, f.object, f.source, f.valid_at, e.name
                   FROM tkg.facts f
                   JOIN tkg.entities e ON f.subject_id = e.id
                   WHERE f.predicate LIKE ? OR f.object LIKE ? OR e.name LIKE ?
                   LIMIT ?""",
                (f"%{query}%", f"%{query}%", f"%{query}%", limit),
            ).fetchall()
            for r in rows:
                results.append({
                    "source": "temporal_kg",
                    "key": "{} {}".format(r["name"], r["predicate"]),
                    "content": r["object"],
                    "domain": "kg",
                    "created_at": r["valid_at"],
                })
        except Exception:
            pass

    finally:
        conn.close()

    return sorted(results, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]


def get_entity_graph(entity_name: str) -> Dict:
    """Get all facts and relationships for an entity across databases."""
    conn = get_unified_conn()
    result = {"entity": entity_name, "facts": [], "decisions": [], "tasks": []}

    try:
        rows = conn.execute(
            """SELECT f.predicate, f.object, f.source, f.valid_at, f.confidence
               FROM tkg.facts f
               JOIN tkg.entities e ON f.subject_id = e.id
               WHERE e.name = ? ORDER BY f.valid_at DESC""",
            (entity_name,),
        ).fetchall()
        result["facts"] = [dict(r) for r in rows]

        rows = conn.execute(
            """SELECT summary, domain, outcome, created_at
               FROM decisions.decisions
               WHERE summary LIKE ? OR domain LIKE ?
               ORDER BY created_at DESC""",
            (f"%{entity_name}%", f"%{entity_name}%"),
        ).fetchall()
        result["decisions"] = [dict(r) for r in rows]

        rows = conn.execute(
            """SELECT id, title, status, assignee, created_at
               FROM kanban.tasks
               WHERE title LIKE ? OR body LIKE ?
               ORDER BY created_at DESC""",
            (f"%{entity_name}%", f"%{entity_name}%"),
        ).fetchall()
        result["tasks"] = [dict(r) for r in rows]

    finally:
        conn.close()

    return result


def get_cross_domain_summary() -> Dict:
    """Get a high-level summary of knowledge across all databases."""
    conn = get_unified_conn()
    summary = {}

    try:
        queries = {
            "entities": "SELECT COUNT(*) as cnt FROM tkg.entities",
            "facts": "SELECT COUNT(*) as cnt FROM tkg.facts",
            "memory_entries": "SELECT COUNT(*) as cnt FROM unified_memory.memory_store",
            "active_tasks": "SELECT COUNT(*) as cnt FROM kanban.tasks WHERE status NOT IN (\"done\", \"cancelled\")",
            "active_decisions": "SELECT COUNT(*) as cnt FROM decisions.decisions WHERE status = \"active\"",
        }
        for key, sql in queries.items():
            try:
                r = conn.execute(sql).fetchone()
                summary[key] = r["cnt"] if r else 0
            except Exception:
                summary[key] = 0

        # Recent observations (7 days)
        try:
            cutoff = (datetime.now() - timedelta(days=7)).timestamp()
            r = conn.execute("SELECT COUNT(*) as cnt FROM cmem.observations WHERE timestamp > ?", (cutoff,)).fetchone()
            summary["recent_observations"] = r["cnt"] if r else 0
        except Exception:
            summary["recent_observations"] = 0

    finally:
        conn.close()

    return summary


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"

    if cmd == "summary":
        s = get_cross_domain_summary()
        for k, v in s.items():
            print(f"  {k}: {v}")

    elif cmd == "search" and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        results = search_all(query)
        for r in results:
            print("  [{}] {}: {}".format(r["source"], r["key"], r["content"][:100]))

    elif cmd == "entity" and len(sys.argv) > 2:
        name = sys.argv[2]
        g = get_entity_graph(name)
        print(json.dumps(g, indent=2, default=str))
