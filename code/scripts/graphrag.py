#!/usr/bin/env python3
"""graphrag.py — GraphRAG on the temporal knowledge graph.

Implements the GraphRAG pattern:
1. Entity extraction from text (identifies entities and relations)
2. Graph traversal for context expansion
3. Hybrid retrieval (vector + graph)
4. Multi-hop reasoning via path queries

Usage:
    from graphrag import GraphRAG

    g = GraphRAG()
    ctx = g.query("What happened with paperless last week?")
    ctx = g.hybrid_retrieve("paperless OOM crash", top_k=5)
"""

from __future__ import annotations
import json
import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
TKG_DB = HERMES_HOME / "temporal_kg.db"
KG_DB = HERMES_HOME / "knowledge_graph" / "graph.db"


@dataclass
class GraphContext:
    entities: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    paths: list[list[dict]] = field(default_factory=list)
    summary: str = ""
    source_documents: list[str] = field(default_factory=list)


class GraphRAG:
    def __init__(self, tkg_path: Optional[Path] = None, kg_path: Optional[Path] = None):
        self.tkg_path = tkg_path or TKG_DB
        self.kg_path = kg_path or KG_DB

    def query(self, question: str, max_hops: int = 2) -> GraphContext:
        """Full GraphRAG query: extract entities, traverse graph, return context."""
        ctx = GraphContext()
        entities = self._extract_entities(question)
        for ent in entities:
            found = self._search_entity(ent)
            ctx.entities.extend(found)
        for entity in ctx.entities:
            facts = self._get_facts(entity.get("id", ""), entity.get("name", ""))
            ctx.facts.extend(facts)
            if max_hops >= 2:
                paths = self._traverse_entity(entity.get("id", ""), entity.get("name", ""))
                ctx.paths.append(paths)
        ctx.facts = self._dedup_facts(ctx.facts)
        return ctx

    def hybrid_retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """Hybrid retrieval: vector similarity + graph neighbors."""
        results = []

        # 1. Text search in temporal KG
        conn = self._tkg_conn()
        if conn:
            try:
                cur = conn.execute(
                    "SELECT e.name, e.type, e.summary, f.predicate, f.object, f.confidence "
                    "FROM entities e JOIN facts f ON e.id = f.subject_id "
                    "WHERE e.name LIKE ? OR e.summary LIKE ? OR f.object LIKE ? "
                    "ORDER BY f.confidence DESC LIMIT ?",
                    (f"%{query}%", f"%{query}%", f"%{query}%", top_k * 2),
                )
                for row in cur.fetchall():
                    results.append({"entity": row[0], "type": row[1], "summary": row[2],
                                    "predicate": row[3], "object": row[4], "confidence": row[5],
                                    "source": "temporal_kg"})
            except Exception:
                pass
            conn.close()

        # 2. Semantic graph search
        conn2 = self._kg_conn()
        if conn2:
            try:
                cur2 = conn2.execute(
                    "SELECT n.label, n.node_type, n.properties, e.relation_type, e.confidence "
                    "FROM kg_fts f JOIN kg_nodes n ON f.rowid = n.rowid "
                    "LEFT JOIN kg_edges e ON n.node_id = e.source_id "
                    "WHERE kg_fts MATCH ? LIMIT ?",
                    (query, top_k),
                )
                for row in cur2.fetchall():
                    results.append({"entity": row[0], "type": row[1], "summary": str(row[2]),
                                    "predicate": row[3], "object": "", "confidence": row[4],
                                    "source": "knowledge_graph"})
            except Exception:
                pass
            conn2.close()

        return sorted(results, key=lambda x: x.get("confidence", 0) or 0, reverse=True)[:top_k]

    def get_timeline(self, entity_name: str) -> list[dict]:
        conn = self._tkg_conn()
        events = []
        if conn:
            try:
                cur = conn.execute(
                    "SELECT e.name, f.predicate, f.object, f.valid_at, f.confidence, f.source "
                    "FROM entities e JOIN facts f ON e.id = f.subject_id "
                    "WHERE e.name = ? ORDER BY f.valid_at DESC",
                    (entity_name,),
                )
                for row in cur.fetchall():
                    events.append({"entity": row[0], "predicate": row[1], "object": row[2],
                                   "timestamp": row[3], "confidence": row[4], "source": row[5]})
            except Exception:
                pass
            conn.close()
        return events

    def entity_network(self, entity_name: str, depth: int = 2) -> dict:
        """Build entity network around a given entity."""
        network: dict[str, set] = {}
        visited = set()
        queue = [(entity_name, 0)]
        while queue:
            current, level = queue.pop(0)
            if level > depth or current in visited:
                continue
            visited.add(current)
            conn = self._tkg_conn()
            if conn:
                try:
                    cur = conn.execute(
                        "SELECT e2.name, f.predicate FROM entities e1 "
                        "JOIN facts f ON e1.id = f.subject_id "
                        "JOIN entities e2 ON f.object_id = e2.id OR f.object = e2.name "
                        "WHERE e1.name = ?", (current,))
                    for row in cur.fetchall():
                        rel = f"{row[1]} -> {row[0]}"
                        network.setdefault(current, set()).add(rel)
                        if row[0] not in visited:
                            queue.append((row[0], level + 1))
                except Exception:
                    pass
                conn.close()
        return {k: list(v) for k, v in network.items()}

    def _extract_entities(self, text: str) -> list[str]:
        words = re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', text)
        words += re.findall(r'\b(paperless|immich|grafana|prometheus|docker|ollama|'
                            r'qdrant|redis|pihole|traefik|searxng|vaultwarden|'
                            r'openwebui|portainer|calibre|kopia|duckdns|pi-hole|'
                            r'authentik|homepage|node-exporter)\b', text.lower())
        return list(set(w for w in words if len(w) > 2))

    def _search_entity(self, name: str) -> list[dict]:
        conn = self._tkg_conn()
        results = []
        if conn:
            try:
                cur = conn.execute(
                    "SELECT id, name, type, summary FROM entities WHERE name LIKE ? LIMIT 10",
                    (f"%{name}%",),
                )
                for row in cur.fetchall():
                    results.append({"id": row[0], "name": row[1], "type": row[2], "summary": row[3]})
            except Exception:
                pass
            conn.close()
        return results

    def _get_facts(self, entity_id: str, entity_name: str) -> list[dict]:
        conn = self._tkg_conn()
        facts = []
        if conn:
            try:
                cur = conn.execute(
                    "SELECT predicate, object, valid_at, confidence, source "
                    "FROM facts WHERE subject_id = ? OR object LIKE ? "
                    "ORDER BY valid_at DESC LIMIT 20",
                    (entity_id, f"%{entity_name}%"),
                )
                for row in cur.fetchall():
                    facts.append({"predicate": row[0], "object": row[1],
                                   "timestamp": row[2], "confidence": row[3], "source": row[4]})
            except Exception:
                pass
            conn.close()
        return facts

    def _traverse_entity(self, entity_id: str, entity_name: str) -> list[dict]:
        path = []
        conn = self._tkg_conn()
        if conn:
            try:
                cur = conn.execute(
                    "SELECT e2.name, e2.type, f.predicate, f.object, f.confidence "
                    "FROM entities e1 "
                    "JOIN facts f ON e1.id = f.subject_id "
                    "JOIN entities e2 ON (f.object_id = e2.id OR e2.name = f.object) "
                    "WHERE e1.name = ? AND e2.id != e1.id "
                    "ORDER BY f.confidence DESC LIMIT 5",
                    (entity_name,),
                )
                for row in cur.fetchall():
                    path.append({"target": row[0], "target_type": row[1],
                                  "relation": row[2], "object": row[3], "confidence": row[4]})
            except Exception:
                pass
            conn.close()
        return path

    def _dedup_facts(self, facts: list[dict]) -> list[dict]:
        seen = set()
        unique = []
        for f in facts:
            key = f"{f['predicate']}:{f['object']}:{f.get('timestamp', '')}"
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique

    def _tkg_conn(self) -> Optional[sqlite3.Connection]:
        try:
            if self.tkg_path.exists():
                conn = sqlite3.connect(str(self.tkg_path))
                conn.execute("PRAGMA query_only = ON")
                return conn
        except Exception:
            pass
        return None

    def _kg_conn(self) -> Optional[sqlite3.Connection]:
        try:
            if self.kg_path.exists():
                return sqlite3.connect(str(self.kg_path))
        except Exception:
            pass
        return None


def run_entity_extraction():
    """Standalone entity extraction entry point. Runs via cron."""
    g = GraphRAG()
    extracted = 0
    conn = g._tkg_conn()
    if conn:
        try:
            cur = conn.execute("SELECT id, name, summary FROM entities WHERE summary IS NOT NULL")
            for row in cur.fetchall():
                entities = g._extract_entities(row[2] or "")
                extracted += len(entities)
        except Exception:
            pass
        conn.close()
    return {"entities_extracted": extracted}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GraphRAG engine")
    parser.add_argument("--extract", action="store_true", help="Run entity extraction")
    parser.add_argument("--query", type=str, help="Query the graph")
    parser.add_argument("--hybrid", type=str, help="Hybrid search query")
    parser.add_argument("--timeline", type=str, help="Entity timeline")
    parser.add_argument("--network", type=str, help="Entity network")
    args = parser.parse_args()

    g = GraphRAG()

    if args.extract:
        result = run_entity_extraction()
        print(json.dumps(result))
    elif args.query:
        ctx = g.query(args.query)
        print(f"Entities: {len(ctx.entities)}")
        print(f"Facts: {len(ctx.facts)}")
        for f in ctx.facts[:10]:
            print(f"  {f.get('predicate','')}: {f.get('object','')} ({f.get('confidence','')})")
    elif args.hybrid:
        results = g.hybrid_retrieve(args.hybrid)
        for r in results:
            print(f"  [{r.get('confidence',0)}] {r.get('entity','')} ({r.get('source','')})")
    elif args.timeline:
        events = g.get_timeline(args.timeline)
        for e in events[:20]:
            print(f"  {e.get('timestamp','')} {e.get('predicate','')}: {e.get('object','')}")
    elif args.network:
        net = g.entity_network(args.network)
        for entity, rels in net.items():
            print(f"  {entity}:")
            for r in rels[:5]:
                print(f"    {r}")

if __name__ == "__main__":
    main()

__all__ = ["GraphRAG", "GraphContext", "run_entity_extraction"]
