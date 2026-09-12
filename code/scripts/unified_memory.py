#!/usr/bin/env python3
"""
unified_memory.py — Consolidated memory service for Hermes.

MERGES: hermes_memory.py (SQLite + Qdrant) + temporal_kg.py (Temporal KG)
REPLACES: 2 of 6 memory cron jobs (memory_cleanup, temporal_ingest)

All data routed to appropriate backend automatically:
- Vector (Qdrant) for semantic search
- Relational (SQLite) for structured data + metadata
- Graph (Temporal KG) for entity-relation + time-series queries

Usage:
    from unified_memory import UnifiedMemory

    mem = UnifiedMemory()
    mem.store("pref", {"key": "theme", "value": "dark"}, domain="PERSONAL")
    results = mem.search("dark theme", top_k=5)
    mem.remember("paperless", "crashed", "2026-07-10", confidence=0.9)
    timeline = mem.timeline("paperless")
    mem.ingest_capsules()       # runs temporal KG ingestion
    mem.ingest_health()         # runs health dashboard ingestion
    mem.prune()                 # cleanup old entries
"""

from __future__ import annotations
import json
import os
import re
import sqlite3
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
UNIFIED_DB = HERMES_HOME / "data" / "unified_memory.db"
TKG_DB = HERMES_HOME / "temporal_kg.db"
CAPSULE_FILE = HERMES_HOME / "capsules" / "outcomes.jsonl"
HEALTH_DASH_FILE = HERMES_HOME / "state" / "health_dashboard.json"
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")

# ══════════════════════════════════════════════════════════════════════════════
# Schema — unified memory store + temporal KG
# ══════════════════════════════════════════════════════════════════════════════

SCHEMA_SQL = """
-- Unified memory store (replaces hermes_memory.py tables)
CREATE TABLE IF NOT EXISTS memory_store (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL DEFAULT 'default',
    key TEXT NOT NULL,
    value TEXT,
    domain TEXT DEFAULT '',
    source TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    ttl_seconds INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}',
    UNIQUE(namespace, key)
);
CREATE INDEX IF NOT EXISTS idx_memory_namespace ON memory_store(namespace);
CREATE INDEX IF NOT EXISTS idx_memory_domain ON memory_store(domain);
CREATE INDEX IF NOT EXISTS idx_memory_key ON memory_store(key);

CREATE TABLE IF NOT EXISTS memory_tags (
    memory_id INTEGER REFERENCES memory_store(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (memory_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_memory_tags_tag ON memory_tags(tag);

CREATE TABLE IF NOT EXISTS memory_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER REFERENCES memory_store(id) ON DELETE CASCADE,
    embedding BLOB,
    model TEXT DEFAULT 'text-embedding-ada-002',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memory_stats (
    metric TEXT PRIMARY KEY,
    value REAL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    key, value, domain,
    content='memory_store',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS memory_fts_insert AFTER INSERT ON memory_store BEGIN
    INSERT INTO memory_fts(rowid, key, value, domain) VALUES (new.id, new.key, new.value, new.domain);
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_delete AFTER DELETE ON memory_store BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, key, value, domain) VALUES ('delete', old.id, old.key, old.value, old.domain);
END;

-- Temporal Knowledge Graph (from temporal_kg.py)
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT DEFAULT 'service',
    summary TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    valid_at TEXT NOT NULL,
    invalid_at TEXT,
    source TEXT DEFAULT 'capsule',
    confidence REAL DEFAULT 1.0,
    FOREIGN KEY (subject_id) REFERENCES entities(id)
);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject_id);
CREATE INDEX IF NOT EXISTS idx_facts_predicate ON facts(predicate);
CREATE INDEX IF NOT EXISTS idx_facts_valid ON facts(valid_at);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);

-- Decisions table (for tracking important decisions)
CREATE TABLE IF NOT EXISTS decisions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT, domain TEXT, outcome TEXT, created TEXT, valid_at TEXT
);
"""


# ══════════════════════════════════════════════════════════════════════════════
# Data Classes
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class MemoryResult:
    key: str = ""
    value: Any = None
    domain: str = ""
    namespace: str = "default"
    source: str = ""
    created_at: str = ""
    tags: list[str] = field(default_factory=list)
    score: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class Fact:
    entity: str
    predicate: str
    object: str
    valid_at: str
    source: str
    confidence: float


# ══════════════════════════════════════════════════════════════════════════════
# Unified Memory Service
# ══════════════════════════════════════════════════════════════════════════════

class UnifiedMemory:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or UNIFIED_DB
        self.tkg_path = TKG_DB
        self._init_db()
        self._qdrant_available = self._check_qdrant()

    # ══════════════════════════════════════════════════════════════════════════════
    # PUBLIC API — Unified Memory Store (from hermes_memory.py)
    # ══════════════════════════════════════════════════════════════════════════════

    def store(self, namespace: str, data: dict, domain: str = "",
              key: Optional[str] = None, tags: Optional[list[str]] = None,
              ttl_seconds: int = 0, source: str = ""):
        """Store a value in the unified memory store."""
        key = key or data.get("key", data.get("name", str(hash(str(data)))))
        tags = tags or []
        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO memory_store(namespace, key, value, domain, source, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(namespace, key) DO UPDATE SET "
                "value=excluded.value, domain=excluded.domain, source=excluded.source, "
                "metadata=excluded.metadata, updated_at=datetime('now')",
                (namespace, key, json.dumps(data), domain, source,
                 json.dumps({"tags": tags, "ttl": ttl_seconds})),
            )
            row_id = conn.execute("SELECT id FROM memory_store WHERE namespace=? AND key=?",
                                  (namespace, key)).fetchone()[0]
            for tag in tags:
                conn.execute("INSERT OR IGNORE INTO memory_tags(memory_id, tag) VALUES (?, ?)", (row_id, tag))
            conn.commit()
        finally:
            conn.close()

    def get(self, namespace: str, key: str) -> Optional[MemoryResult]:
        """Get a value from the unified memory store."""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT key, value, domain, namespace, source, created_at, metadata "
                "FROM memory_store WHERE namespace=? AND key=?", (namespace, key)
            ).fetchone()
            if row:
                meta = json.loads(row[6] or "{}")
                tags_row = conn.execute(
                    "SELECT tag FROM memory_tags WHERE memory_id IN (SELECT id FROM memory_store WHERE namespace=? AND key=?)",
                    (namespace, key)).fetchall()
                return MemoryResult(
                    key=row[0], value=json.loads(row[1]), domain=row[2],
                    namespace=row[3], source=row[4], created_at=row[5],
                    tags=[t[0] for t in tags_row], metadata=meta,
                )
        finally:
            conn.close()
        return None

    def search(self, query: str, domain: str = "", top_k: int = 10) -> list[MemoryResult]:
        """Search memory using FTS5 text search + optional Qdrant + temporal KG fallback."""
        results = []

        # 1. FTS5 text search (only alpha/digit tokens; hyphen/dot break FTS5)
        tokens = [re.sub(r"[^\w]", "", t) for t in query.split()]
        tokens = [t for t in tokens if len(t) > 1]
        if tokens:
            conn = self._conn()
            try:
                fts_query = " OR ".join(tokens)
                if domain:
                    rows = conn.execute(
                        "SELECT m.key, m.value, m.domain, m.namespace, m.source, m.created_at, m.metadata "
                        "FROM memory_fts f JOIN memory_store m ON f.rowid = m.id "
                        "WHERE memory_fts MATCH ? AND m.domain = ? "
                        "ORDER BY rank LIMIT ?",
                        (fts_query, domain, top_k),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT m.key, m.value, m.domain, m.namespace, m.source, m.created_at, m.metadata "
                        "FROM memory_fts f JOIN memory_store m ON f.rowid = m.id "
                        "WHERE memory_fts MATCH ? ORDER BY rank LIMIT ?",
                        (fts_query, top_k),
                    ).fetchall()
                for row in rows:
                    meta = json.loads(row[6] or "{}")
                    tags_row = conn.execute(
                        "SELECT tag FROM memory_tags WHERE memory_id IN (SELECT id FROM memory_store WHERE key=? AND namespace=?)",
                        (row[0], row[3])).fetchall()
                    results.append(MemoryResult(
                        key=row[0], value=json.loads(row[1]), domain=row[2],
                        namespace=row[3], source=row[4], created_at=row[5],
                        tags=[t[0] for t in tags_row], metadata=meta, score=1.0,
                    ))
            except Exception:
                results = []
            finally:
                conn.close()

        # 1b. Fallback: naive substring match on the store if FTS failed/empty
        if not results:
            conn = self._conn()
            try:
                conn.execute("CREATE TEMP TABLE IF NOT EXISTS _t (id INTEGER PRIMARY KEY);")
                rows = conn.execute(
                    "SELECT key, value, domain, namespace, source, created_at, metadata "
                    "FROM memory_store WHERE key LIKE ? OR value LIKE ? "
                    "LIMIT ?",
                    (f"%{query}%", f"%{query}%", top_k),
                ).fetchall()
                for row in rows:
                    results.append(MemoryResult(
                        key=row[0], value=json.loads(row[1]), domain=row[2],
                        namespace=row[3], source=row[4], created_at=row[5], score=0.5,
                    ))
            except Exception:
                pass
            finally:
                conn.close()

        # 2. Vector search via Qdrant (if available)
        if self._qdrant_available and not results:
            try:
                vec_results = self._qdrant_search(query, top_k - len(results))
                for vr in vec_results:
                    results.append(MemoryResult(
                        key=vr.get("key", ""), value=vr, domain=vr.get("domain", ""),
                        source="qdrant", score=vr.get("score", 0.5),
                    ))
            except Exception:
                pass

        # 3. Temporal KG fallback (entities + facts) when otherwise empty
        if not results:
            try:
                results.extend(self._search_tkg(query, top_k))
            except Exception:
                pass

        return results[:top_k]

    def _search_tkg(self, query: str, limit: int) -> list:
        """Query the temporal knowledge graph (entities + facts) as MemoryResult entries."""
        conn = self._tkg_conn()
        try:
            kws = [w for w in query.lower().split() if len(w) > 2]
            entities = []
            if kws:
                like = "%" + "%".join(kws) + "%"
                rows = conn.execute("""
                    SELECT id, name, summary FROM entities
                    WHERE name LIKE ? OR summary LIKE ? ORDER BY updated_at DESC LIMIT ?
                """, (f"%{query}%", f"%{query}%", limit)).fetchall()
                for rid, name, summary in rows:
                    entities.append((rid, name, summary, None, None))
                # facts where entity/object match
                frows = conn.execute("""
                    SELECT e.name, f.predicate, f.object FROM facts f
                    JOIN entities e ON f.subject_id = e.id
                    WHERE e.name LIKE ? OR f.object LIKE ? OR f.predicate LIKE ?
                    ORDER BY f.valid_at DESC LIMIT ?
                """, (f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()
                entities.extend(frows)
        finally:
            conn.close()
        out, seen = [], set()
        for row in entities:
            if len(row) == 5:
                rid, ename, summary = row[0], row[1], row[2]
                key = f"kg::{ename.lower()}"
                text = summary or ename
            else:
                ename, pred, obj = row
                key = f"kg::{ename.lower()}::{pred.lower()}"
                text = f"{ename} {pred}: {obj}"[:300]
            if key in seen:
                continue
            seen.add(key)
            out.append(MemoryResult(
                key=key, value={"entity": ename, "text": text},
                domain="tkg", namespace="knowledge", source="temporal_kg", score=0.6,
            ))
        return out[:limit]


    # ══════════════════════════════════════════════════════════════════════════════
    # PUBLIC API — Temporal Knowledge Graph (from temporal_kg.py)
    # ══════════════════════════════════════════════════════════════════════════════

    def remember(self, subject: str, predicate: str, object_val: str,
                 confidence: float = 0.8, source: str = "unified_memory"):
        """Store a fact in the temporal KG."""
        conn = self._tkg_conn()
        try:
            entity_id = subject.replace("-", "_").replace(".", "_")
            now = datetime.now().isoformat()

            # Upsert entity
            self._upsert_entity(conn, entity_id, subject, "service", f"Last: {object_val}", now)

            # Insert fact
            conn.execute(
                "INSERT INTO facts (subject_id, predicate, object, valid_at, source, confidence) VALUES (?, ?, ?, ?, ?, ?)",
                (entity_id, predicate, object_val, now, source, confidence),
            )
            conn.commit()
        finally:
            conn.close()

    def timeline(self, entity: str, limit: int = 20) -> list[dict]:
        """Get timeline of facts about an entity."""
        conn = self._tkg_conn()
        try:
            entity_id = entity.replace("-", "_").replace(".", "_")
            rows = conn.execute("""
                SELECT f.predicate, f.object, f.valid_at, f.source, f.confidence
                FROM facts f JOIN entities e ON f.subject_id = e.id
                WHERE e.id = ? OR e.name = ?
                ORDER BY f.valid_at DESC LIMIT ?
            """, (entity_id, entity, limit)).fetchall()
            return [
                {"predicate": r[0], "object": r[1], "valid_at": r[2], "source": r[3], "confidence": r[4]}
                for r in rows
            ]
        finally:
            conn.close()

    def query_facts(self, query: str, limit: int = 10) -> list[Fact]:
        """Query facts by keyword matching."""
        conn = self._tkg_conn()
        keywords = [w for w in query.lower().split() if len(w) > 2]
        if not keywords:
            conn.close()
            return []

        results = []
        seen = set()
        for kw in keywords:
            rows = conn.execute("""
                SELECT e.name, f.predicate, f.object, f.valid_at, f.source, f.confidence
                FROM facts f JOIN entities e ON f.subject_id = e.id
                WHERE e.name LIKE ? OR f.object LIKE ? OR f.predicate LIKE ?
                ORDER BY f.valid_at DESC LIMIT ?
            """, (f"%{kw}%", f"%{kw}%", f"%{kw}%", limit)).fetchall()

            for row in rows:
                key = (row[0], row[1], row[2])
                if key not in seen:
                    seen.add(key)
                    results.append(Fact(
                        entity=row[0], predicate=row[1], object=row[2],
                        valid_at=row[3], source=row[4], confidence=row[5],
                    ))
        conn.close()
        return results[:limit]

    def add_decision(self, summary: str, domain: str, outcome: str) -> int:
        """Add a decision to the temporal KG."""
        conn = self._tkg_conn()
        try:
            now = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO decisions (summary, domain, outcome, created, valid_at) VALUES (?, ?, ?, ?, ?)",
                (summary, domain, outcome, now, now),
            )
            did = cur.lastrowid
            conn.commit()
            return did
        finally:
            conn.close()

    def query_decisions(self, outcome_filter: str = None, domain_filter: str = None) -> list[dict]:
        """Query decisions from temporal KG."""
        conn = self._tkg_conn()
        where, args = [], []
        if outcome_filter:
            where.append("outcome LIKE ?"); args.append(f"%{outcome_filter}%")
        if domain_filter:
            where.append("domain LIKE ?"); args.append(f"%{domain_filter}%")

        sql = "SELECT summary, domain, outcome, created FROM decisions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created DESC LIMIT 20"

        rows = conn.execute(sql, args).fetchall()
        conn.close()
        return [{"summary": r[0], "domain": r[1], "outcome": r[2], "created": r[3]} for r in rows]

    # ══════════════════════════════════════════════════════════════════════════════
    # PUBLIC API — Ingestion (from temporal_kg.py)
    # ══════════════════════════════════════════════════════════════════════════════

    def ingest_capsules(self, capsule_file: str = "") -> int:
        """Ingest capsule outcomes into the temporal KG. Replaces temporal_kg.py ingest-capsules."""
        capsule_file = capsule_file or str(CAPSULE_FILE)
        cpath = Path(capsule_file)
        if not cpath.exists():
            print(f"No capsule file at {capsule_file}")
            return 0

        conn = self._conn()  # Use main DB which has entities/facts tables
        count = 0
        now = datetime.now().isoformat()

        for line in cpath.read_text().splitlines():
            if not line.strip():
                continue
            try:
                c = json.loads(line)
            except json.JSONDecodeError:
                continue

            target = c.get("target", "unknown")
            gene = c.get("gene_id", "unknown")
            outcome = c.get("outcome", "unknown")
            ts = c.get("timestamp", now)
            notes = c.get("notes", "")
            entity_id = str(target).replace("-", "_").replace(".", "_").replace(" ", "_")

            # Upsert entity
            self._upsert_entity(conn, entity_id, target, "service", f"Last: {outcome}", ts)

            # Insert fact
            conn.execute(
                "INSERT INTO facts (subject_id, predicate, object, valid_at, source, confidence) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(subject_id, predicate, object, valid_at) DO NOTHING",
                (entity_id, f"fix_attempt_{gene}", outcome, ts, c.get("source", "capsule"), 1.0 if outcome == "success" else 0.5),
            )

            # Add notes as a fact if present
            if notes:
                conn.execute(
                    "INSERT INTO facts (subject_id, predicate, object, valid_at, source) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(subject_id, predicate, object, valid_at) DO NOTHING",
                    (entity_id, "has_note", notes[:200], ts, "capsule"),
                )

            count += 1

        conn.commit()
        conn.close()
        print(f"Ingested {count} capsule records into temporal KG")
        return count

    def ingest_health(self, state_dir: str = "") -> bool:
        """Ingest health dashboard snapshots. Replaces temporal_kg.py ingest-health."""
        state_dir = state_dir or str(HERMES_HOME / "state")
        dash_file = Path(state_dir) / "health_dashboard.json"
        if not dash_file.exists():
            return False

        conn = self._tkg_conn()
        now = datetime.now().isoformat()

        try:
            dash = json.loads(dash_file.read_text())
            score = dash.get("health_score", 100)

            # Upsert homelab entity
            self._upsert_entity(conn, "homelab", "homelab", "system", f"Health: {score}/100", now)

            conn.execute(
                "INSERT INTO facts (subject_id, predicate, object, valid_at, source) VALUES (?, ?, ?, ?, ?)",
                ("homelab", "health_score", str(score), now, "health_dashboard"),
            )

            # Ingest individual check results
            for name, check in dash.get("checks", {}).items():
                if isinstance(check, dict):
                    status = check.get("status", "unknown")
                    entity_id = name.replace("-", "_").replace(".", "_")
                    conn.execute(
                        "INSERT OR IGNORE INTO entities (id, name, type, summary, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (entity_id, name, "check", f"Status: {status}", now, now),
                    )
                    conn.execute(
                        "INSERT INTO facts (subject_id, predicate, object, valid_at, source) VALUES (?, ?, ?, ?, ?)",
                        (entity_id, "check_status", status, now, "health_dashboard"),
                    )

            conn.commit()
        except (json.JSONDecodeError, Exception) as e:
            print(f"Health dashboard ingest error: {e}")
        finally:
            conn.close()
        return True

    # ══════════════════════════════════════════════════════════════════════════════
    # PUBLIC API — Maintenance
    # ══════════════════════════════════════════════════════════════════════════════

    def get_stats(self) -> dict:
        """Get combined stats for all backends."""
        # Unified memory store stats
        conn = self._conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM memory_store").fetchone()[0]
            by_domain = conn.execute(
                "SELECT domain, COUNT(*) as c FROM memory_store WHERE domain != '' GROUP BY domain ORDER BY c DESC"
            ).fetchall()
            by_namespace = conn.execute(
                "SELECT namespace, COUNT(*) as c FROM memory_store GROUP BY namespace ORDER BY c DESC"
            ).fetchall()
            recent = conn.execute(
                "SELECT COUNT(*) FROM memory_store WHERE updated_at > datetime('now', '-24 hours')"
            ).fetchone()[0]
        finally:
            conn.close()

        # Temporal KG stats
        conn = self._tkg_conn()
        try:
            entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            fact_count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            sources = dict(conn.execute("SELECT source, COUNT(*) FROM facts GROUP BY source").fetchall())
            entity_types = dict(conn.execute("SELECT type, COUNT(*) FROM entities GROUP BY type").fetchall())
        finally:
            conn.close()

        return {
            "unified_store": {
                "total_entries": total,
                "entries_by_domain": dict(by_domain),
                "entries_by_namespace": dict(by_namespace),
                "added_last_24h": recent,
            },
            "temporal_kg": {
                "entities": entity_count,
                "facts": fact_count,
                "by_source": sources,
                "by_type": entity_types,
            },
            "qdrant_available": self._qdrant_available,
            "db_path": str(self.db_path),
            "tkg_path": str(self.tkg_path),
        }

    def cleanup_expired(self) -> int:
        """Clean up expired TTL entries."""
        conn = self._conn()
        try:
            cur = conn.execute(
                "DELETE FROM memory_store WHERE ttl_seconds > 0 "
                "AND datetime('now') > datetime(created_at, '+' || ttl_seconds || ' seconds')"
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def prune(self, max_entries: int = 50000) -> int:
        """Prune old entries to keep DB size bounded."""
        conn = self._conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM memory_store").fetchone()[0]
            if total <= max_entries:
                return 0
            excess = total - max_entries
            conn.execute(
                "DELETE FROM memory_store WHERE id IN ("
                "SELECT id FROM memory_store ORDER BY updated_at ASC LIMIT ?)", (excess,))
            conn.commit()
            return excess
        finally:
            conn.close()

    # ══════════════════════════════════════════════════════════════════════════════
    # INTERNAL
    # ══════════════════════════════════════════════════════════════════════════════

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.tkg_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _tkg_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.tkg_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _upsert_entity(self, conn, entity_id: str, name: str, etype: str,
                       summary: str, ts: str) -> None:
        conn.execute(
            "INSERT INTO entities (id, name, type, summary, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET summary=excluded.summary, updated_at=excluded.updated_at",
            (entity_id, name, etype, summary[:500], ts, ts),
        )

    def _check_qdrant(self) -> bool:
        try:
            req = urllib.request.Request(f"{QDRANT_URL}/collections", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _qdrant_search(self, query: str, top_k: int) -> list[dict]:
        try:
            body = json.dumps({
                "vector": self._simple_embed(query),
                "limit": top_k,
            }).encode()
            req = urllib.request.Request(
                f"{QDRANT_URL}/collections/memory/points/search",
                data=body, headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                return [p.get("payload", {}) for p in data.get("result", [])]
        except Exception:
            return []

    def _simple_embed(self, text: str) -> list[float]:
        import hashlib
        h = hashlib.sha256(text.encode()).digest()
        return [b / 255.0 for b in h[:384]]


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Unified memory service (store + temporal KG)")
    subparsers = parser.add_subparsers(dest="command")

    # Store commands
    store_p = subparsers.add_parser("store", help="Store a value")
    store_p.add_argument("namespace")
    store_p.add_argument("key")
    store_p.add_argument("value")
    store_p.add_argument("--domain", default="")
    store_p.add_argument("--tags", nargs="*", default=[])
    store_p.add_argument("--ttl", type=int, default=0)

    get_p = subparsers.add_parser("get", help="Get a value")
    get_p.add_argument("namespace")
    get_p.add_argument("key")

    search_p = subparsers.add_parser("search", help="Search memory")
    search_p.add_argument("query")
    search_p.add_argument("--domain", default="")
    search_p.add_argument("--top-k", type=int, default=10)

    # Temporal KG commands
    remember_p = subparsers.add_parser("remember", help="Store a fact in temporal KG")
    remember_p.add_argument("--subject", required=True)
    remember_p.add_argument("--predicate", required=True)
    remember_p.add_argument("--object", required=True)
    remember_p.add_argument("--confidence", type=float, default=0.8)
    remember_p.add_argument("--source", default="unified_memory")

    timeline_p = subparsers.add_parser("timeline", help="Get entity timeline")
    timeline_p.add_argument("entity")
    timeline_p.add_argument("--limit", type=int, default=20)

    query_p = subparsers.add_parser("query", help="Query facts")
    query_p.add_argument("query")
    query_p.add_argument("--limit", type=int, default=10)

    decision_p = subparsers.add_parser("add-decision", help="Add a decision")
    decision_p.add_argument("--summary", required=True)
    decision_p.add_argument("--domain", default="general")
    decision_p.add_argument("--outcome", required=True)

    decisions_p = subparsers.add_parser("decisions", help="Query decisions")
    decisions_p.add_argument("--outcome")
    decisions_p.add_argument("--domain")

    # Ingestion
    subparsers.add_parser("ingest-capsules", help="Ingest capsule outcomes")
    subparsers.add_parser("ingest-health", help="Ingest health dashboard")

    # Maintenance
    prune_p = subparsers.add_parser("prune", help="Prune old entries")
    prune_p.add_argument("--max", type=int, default=50000)

    subparsers.add_parser("cleanup", help="Cleanup expired TTL entries")
    subparsers.add_parser("stats", help="Show stats")

    args = parser.parse_args()

    mem = UnifiedMemory()

    if args.command == "store":
        mem.store(args.namespace, {"key": args.key, "value": args.value}, domain=args.domain, tags=args.tags, ttl_seconds=args.ttl)
        print(f"Stored {args.namespace}/{args.key}")
    elif args.command == "get":
        result = mem.get(args.namespace, args.key)
        if result:
            print(json.dumps({"key": result.key, "value": result.value, "domain": result.domain}, indent=2))
        else:
            print("Not found")
    elif args.command == "search":
        results = mem.search(args.query, domain=args.domain, top_k=args.top_k)
        for r in results:
            print(f"  [{r.score:.2f}] {r.key} ({r.domain})")
    elif args.command == "remember":
        mem.remember(args.subject, args.predicate, args.object, args.confidence, args.source)
        print(f"Remembered: {args.subject} {args.predicate} {args.object}")
    elif args.command == "timeline":
        entries = mem.timeline(args.entity, args.limit)
        for e in entries:
            print(f"  [{e['valid_at'][:19]}] {e['predicate']}: {e['object']}")
        if not entries:
            print(f"No timeline entries for {args.entity}.")
    elif args.command == "query":
        results = mem.query_facts(args.query, args.limit)
        for r in results:
            print(f"  [{r.valid_at[:19]}] {r.entity}: {r.predicate} → {r.object}")
        if not results:
            print("No matching facts found.")
    elif args.command == "add-decision":
        did = mem.add_decision(args.summary, args.domain, args.outcome)
        print(f"Added decision #{did}")
    elif args.command == "decisions":
        for d in mem.query_decisions(args.outcome, args.domain):
            print(f"  [{d['created'][:10]}] {d['domain']}: {d['summary'][:50]}... → {d['outcome']}")
    elif args.command == "ingest-capsules":
        mem.ingest_capsules()
    elif args.command == "ingest-health":
        mem.ingest_health()
    elif args.command == "prune":
        removed = mem.prune(args.max)
        print(f"Pruned {removed} entries")
    elif args.command == "cleanup":
        removed = mem.cleanup_expired()
        print(f"Cleaned {removed} expired entries")
    elif args.command == "stats":
        print(json.dumps(mem.get_stats(), indent=2, default=str))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

__all__ = ["UnifiedMemory", "MemoryResult", "Fact"]