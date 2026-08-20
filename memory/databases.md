---
created: 2026-07-17
updated: 2026-08-20
confidence: high
source: filesystem inventory
---

# Homelab Memory & Database Index

The homelab has a consolidated memory infrastructure. Legacy stores have been migrated to Neo4j agent-memory and Metronix.

## Which Store For What

| You want... | Go to... | How to query |
|-------------|----------|-------------|
| Chat history, sessions | state.db (228 MB, source of truth) | sqlite3 ~/.hermes/state.db |
| Graph-backed memory | Neo4j agent-memory (port 8099) | MCP tools: entity_add, memory_search, etc. |
| Semantic search, RAG | Metronix (port 8086) | API: http://127.0.0.1:8086/api/v1/chat |
| Decision register | data/decisions.db (52 KB) | sqlite3 ~/.hermes/data/decisions.db |
| Personal data | data/personal.db (80 KB) | sqlite3 ~/.hermes/data/personal.db |

## Store consolidation status

As of 2026-08-20, all legacy memory stores have been consolidated:
- Neo4j agent-memory: 427 nodes, 380 relationships
- Metronix: Hybrid RAG (populates automatically)
- Legacy backup: ~/.hermes/legacy_memory_backup/

## Removed infrastructure (2026-08-20)

- Qdrant, MenteDB, legacy memory stores
