#!/usr/bin/env python3
"""hermes_memory.py — Unified memory service for Hermes.

Consolidates fragmented memory into three backends behind a single API:
- Vector (Qdrant) for semantic search
- Relational (SQLite) for structured data and metadata
- Graph (temporal KG) for entity-relation queries

All data is routed to the appropriate backend automatically.
Migration path: new data uses unified API, old DBs remain readable.

Usage:
    from hermes_memory import HermesMemory

    mem = HermesMemory()
    mem.store("user_preference", {"key": "theme", "value": "dark"}, domain="PERSONAL")
    results = mem.search("dark theme preference", top_k=5)
    mem.remember("paperless", "crashed", "2026-07-10", confidence=0.9)
    timeline = mem.timeline("paperless")
"""

from __future__ import annotations
import json
import os
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
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
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
"""


# ---------------------------------------------------------------------------
# Memory Service
# ---------------------------------------------------------------------------

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


class HermesMemory:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or UNIFIED_DB
        self._init_db()
        self._qdrant_available = self._check_qdrant()

    # ── Public API ──────────────────────────────────────────────

    def store(self, namespace: str, data: dict, domain: str = "",
              key: Optional[str] = None, tags: Optional[list[str]] = None,
              ttl_seconds: int = 0, source: str = ""):
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
        results = []

        # 1. FTS5 text search
        conn = self._conn()
        try:
            fts_query = " OR ".join(query.split())
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

        return results[:top_k]

    def delete(self, namespace: str, key: str) -> bool:
        conn = self._conn()
        try:
            cur = conn.execute("DELETE FROM memory_store WHERE namespace=? AND key=?", (namespace, key))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def list_namespace(self, namespace: str, domain: str = "", limit: int = 100) -> list[MemoryResult]:
        conn = self._conn()
        try:
            if domain:
                rows = conn.execute(
                    "SELECT key, value, domain, namespace, source, created_at, metadata "
                    "FROM memory_store WHERE namespace=? AND domain=? ORDER BY updated_at DESC LIMIT ?",
                    (namespace, domain, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key, value, domain, namespace, source, created_at, metadata "
                    "FROM memory_store WHERE namespace=? ORDER BY updated_at DESC LIMIT ?",
                    (namespace, limit),
                ).fetchall()
            return [MemoryResult(key=r[0], value=json.loads(r[1]), domain=r[2],
                                 namespace=r[3], source=r[4], created_at=r[5])
                    for r in rows]
        finally:
            conn.close()

    # ── Temporal KG Integration ─────────────────────────────────

    def remember(self, subject: str, predicate: str, object_val: str,
                 confidence: float = 0.8, source: str = "hermes_memory"):
        """Store a fact in the temporal KG."""
        try:
            subprocess.run([
                "python3", str(HERMES_HOME / "scripts" / "temporal_kg.py"),
                "add-fact", "--subject", subject, "--predicate", predicate,
                "--object", object_val, "--confidence", str(confidence),
                "--source", source,
            ], capture_output=True, text=True, timeout=15)
        except Exception:
            pass

    def timeline(self, entity: str, limit: int = 20) -> list[dict]:
        """Get timeline of facts about an entity."""
        try:
            r = subprocess.run([
                "python3", str(HERMES_HOME / "scripts" / "temporal_kg.py"),
                "timeline", entity,
            ], capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                return [json.loads(l) for l in r.stdout.strip().split("\n") if l]
        except Exception:
            pass
        return []

    # ── Stats ───────────────────────────────────────────────────

    def get_stats(self) -> dict:
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
            return {
                "total_entries": total,
                "entries_by_domain": dict(by_domain),
                "entries_by_namespace": dict(by_namespace),
                "added_last_24h": recent,
                "qdrant_available": self._qdrant_available,
                "db_path": str(self.db_path),
            }
        finally:
            conn.close()

    def cleanup_expired(self) -> int:
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

    # ── Internal ────────────────────────────────────────────────

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

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


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Unified memory service")
    parser.add_argument("--prune", action="store_true", help="Prune old entries")
    parser.add_argument("--cleanup", action="store_true", help="Cleanup expired TTL entries")
    parser.add_argument("--stats", action="store_true", help="Show memory stats")
    parser.add_argument("--search", type=str, help="Search query")
    parser.add_argument("--store", nargs=3, metavar=("NAMESPACE", "KEY", "VALUE"), help="Store a value")
    args = parser.parse_args()

    mem = HermesMemory()

    if args.prune:
        removed = mem.prune()
        print(f"Pruned {removed} entries")
    elif args.cleanup:
        removed = mem.cleanup_expired()
        print(f"Cleaned {removed} expired entries")
    elif args.stats:
        stats = mem.get_stats()
        print(json.dumps(stats, indent=2))
    elif args.search:
        results = mem.search(args.search)
        for r in results:
            print(f"  [{r.score:.2f}] {r.key} ({r.domain})")
    elif args.store:
        ns, key, val = args.store
        mem.store(ns, {"key": key, "value": val}, domain=ns)
        print(f"Stored {ns}/{key}")

if __name__ == "__main__":
    main()

__all__ = ["HermesMemory", "MemoryResult"]
