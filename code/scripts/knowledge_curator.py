#!/usr/bin/env python3
"""knowledge_curator.py - Deduplicate, prune, validate, and organize knowledge.

68K facts accumulating without curation = noise eventually drowns signal.
This module finds duplicates, prunes stale facts, validates consistency,
and keeps the knowledge base healthy.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List
from collections import defaultdict

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
CURATOR_DB = DATA_DIR / "knowledge_curator.db"


def get_db():
    conn = sqlite3.connect(str(CURATOR_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS curation_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        entity_type TEXT,
        entity_id TEXT,
        detail TEXT,
        items_affected INTEGER DEFAULT 0,
        timestamp TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS fact_clusters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cluster_key TEXT NOT NULL,
        fact_ids TEXT NOT NULL,
        representative_id INTEGER,
        member_count INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    conn.commit()
    return conn


def find_duplicates():
    """Find potential duplicate facts across temporal_kg."""
    conn_kg = sqlite3.connect(str(HERMES_HOME / "data" / "unified_memory.db"))
    conn_kg.row_factory = sqlite3.Row

    try:
        # Find entities with similar names
        rows = conn_kg.execute(
            """SELECT e1.id as id1, e1.name as name1, e1.type as type1,
                      e2.id as id2, e2.name as name2, e2.type as type2
               FROM entities e1
               JOIN entities e2 ON e1.id < e2.id
               WHERE e1.name = e2.name OR (
                   REPLACE(REPLACE(REPLACE(LOWER(e1.name), '-', ''), '_', ''), ' ', '') =
                   REPLACE(REPLACE(REPLACE(LOWER(e2.name), '-', ''), '_', ''), ' ', '')
               )"""
        ).fetchall()

        duplicates = []
        for r in rows:
            duplicates.append({
                "type": "entity",
                "pair": [dict(r)],
                "reason": "identical names",
            })

        # Find duplicate facts (same subject + predicate + object)
        rows = conn_kg.execute(
            """SELECT f1.id as id1, f1.subject_id, f1.predicate, f1.object,
                      f1.source as source1, f1.valid_at as date1,
                      f2.id as id2, f2.source as source2, f2.valid_at as date2
               FROM facts f1
               JOIN facts f2 ON f1.id < f2.id
               WHERE f1.subject_id = f2.subject_id
               AND f1.predicate = f2.predicate
               AND f1.object = f2.object"""
        ).fetchall()

        for r in rows:
            duplicates.append({
                "type": "fact",
                "id1": r["id1"],
                "id2": r["id2"],
                "reason": "same subject/predicate/object",
                "sources": [r["source1"], r["source2"]],
            })

        return duplicates
    finally:
        conn_kg.close()


def find_stale_facts(max_age_days=90):
    """Find facts that haven't been updated in a long time."""
    conn_kg = sqlite3.connect(str(HERMES_HOME / "data" / "unified_memory.db"))
    conn_kg.row_factory = sqlite3.Row

    try:
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
        rows = conn_kg.execute(
            """SELECT f.id, f.predicate, f.object, f.valid_at, e.name, e.type
               FROM facts f
               JOIN entities e ON f.subject_id = e.id
               WHERE f.valid_at < ?
               ORDER BY f.valid_at ASC
               LIMIT 50""",
            (cutoff,),
        ).fetchall()

        return [{"id": r["id"], "entity": r["name"], "predicate": r["predicate"],
                 "object": r["object"], "age": r["valid_at"]} for r in rows]
    finally:
        conn_kg.close()


def find_orphan_entities():
    """Find entities with no facts."""
    conn_kg = sqlite3.connect(str(HERMES_HOME / "data" / "unified_memory.db"))
    conn_kg.row_factory = sqlite3.Row

    try:
        rows = conn_kg.execute(
            """SELECT e.id, e.name, e.type, e.created_at
               FROM entities e
               LEFT JOIN facts f ON e.id = f.subject_id
               WHERE f.id IS NULL"""
        ).fetchall()

        return [{"id": r["id"], "name": r["name"], "type": r["type"]} for r in rows]
    finally:
        conn_kg.close()


def find_contradictions():
    """Find facts that contradict each other (same subject+predicate, different object)."""
    conn_kg = sqlite3.connect(str(HERMES_HOME / "data" / "unified_memory.db"))
    conn_kg.row_factory = sqlite3.Row

    try:
        rows = conn_kg.execute(
            """SELECT f1.predicate, f1.object as obj1, f1.source as src1, f1.valid_at as date1,
                      f2.object as obj2, f2.source as src2, f2.valid_at as date2,
                      e.name as entity_name
               FROM facts f1
               JOIN facts f2 ON f1.subject_id = f2.subject_id AND f1.predicate = f2.predicate
               JOIN entities e ON f1.subject_id = e.id
               WHERE f1.id < f2.id
               AND f1.object != f2.object"""
        ).fetchall()

        contradictions = []
        for r in rows:
            contradictions.append({
                "entity": r["entity_name"],
                "predicate": r["predicate"],
                "version1": {"object": r["obj1"], "source": r["src1"], "date": r["date1"]},
                "version2": {"object": r["obj2"], "source": r["src2"], "date": r["date2"]},
            })

        return contradictions
    finally:
        conn_kg.close()


def run_curation():
    """Run a full curation cycle."""
    results = {"duplicates": 0, "stale": 0, "orphan": 0, "contradictions": 0}

    duplicates = find_duplicates()
    results["duplicates"] = len(duplicates)

    stale = find_stale_facts()
    results["stale"] = len(stale)

    orphans = find_orphan_entities()
    results["orphan"] = len(orphans)

    contradictions = find_contradictions()
    results["contradictions"] = len(contradictions)

    # Log to curator DB
    conn = get_db()
    now = datetime.now().isoformat()
    for action, count in results.items():
        if count > 0:
            conn.execute(
                """INSERT INTO curation_log (action, detail, items_affected, timestamp)
                   VALUES (?, ?, ?, ?)""",
                (action, f"Found {count} {action}", count, now),
            )
    conn.commit()
    conn.close()

    return results


def get_curation_stats():
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT action, COUNT(*) as runs, SUM(items_affected) as total_affected
               FROM curation_log GROUP BY action"""
        ).fetchall()
        return {r["action"]: {"runs": r["runs"], "total_affected": r["total_affected"] or 0} for r in rows}
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"

    if cmd == "run":
        results = run_curation()
        for k, v in results.items():
            print(f"  {k}: {v}")
    elif cmd == "stats":
        print(json.dumps(get_curation_stats(), indent=2))
    elif cmd == "duplicates":
        for d in find_duplicates()[:10]:
            print(f"  [{d['type']}] {d['reason']}: {d.get('id1')} / {d.get('id2')}")
    elif cmd == "stale":
        for s in find_stale_facts()[:10]:
            print(f"  {s['entity']}: {s['predicate']} = {s['object']} (since {s['age']})")
    elif cmd == "contradictions":
        for c in find_contradictions()[:10]:
            print(f"  {c['entity']}: {c['predicate']}")
            print(f"    {c['version1']['date1']}: {c['version1']['object']} ({c['version1']['source']})")
            print(f"    {c['version2']['date2']}: {c['version2']['object']} ({c['version2']['source']})")
