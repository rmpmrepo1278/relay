---
created: 2026-07-17
confidence: high
source: filesystem inventory
---

# Homelab Memory & Database Index

The homelab has an extensive memory infrastructure. The collaborator memory repo (this one) is the **thin index layer** — human-readable context and cross-tool continuity. For detailed data, query the canonical stores below.

## Which Store For What

| You want... | Go to... | How to query |
|-------------|----------|-------------|
| Unified memory (consolidated: sessions, observations, entities, facts, SOPs, knowledge graph, decisions, habits, tasks, outcomes, reflexions) | **unified_memory.db** (85.6 MB, 60+ tables, consolidated via `hermes_consolidate.py`) | `python3 ~/.hermes/scripts/hermes_consolidate.py` (read-only migration) · query tools via MCP `hermes_entities`, `hermes_shared_facts`, `hermes_recall` |
| Recent sessions, chat history | `state.db` (source of truth, pre-consolidation) | `sqlite3 ~/.hermes/state.db "SELECT * FROM messages ORDER BY id DESC LIMIT 10;"` |
| Observed facts, SOPs, compressed memories | `claudemem.db` (source of truth, pre-consolidation) | `sqlite3 ~/.hermes/claudemem.db "SELECT * FROM observations ORDER BY id DESC LIMIT 10;"` |
| Temporal facts about entities/services | `temporal_kg.db` (source of truth, pre-consolidation) | `python3 ~/.hermes/scripts/temporal_kg.py query "paperless failures"` |
| Semantic relationships (nodes + edges) | `knowledge_graph/graph.db` (source of truth, pre-consolidation) | `sqlite3 ~/.hermes/knowledge_graph/graph.db "SELECT * FROM kg_nodes;"` |
| Shared facts (goals, preferences, context) | `shared_facts.db` (source of truth, pre-consolidation) | `sqlite3 ~/.hermes/shared_facts.db "SELECT * FROM shared_facts;"` |
| Decision register | `data/decisions.db` (source of truth, pre-consolidation) | `sqlite3 ~/.hermes/data/decisions.db "SELECT * FROM decisions;"` |
| Habits, projects, health, finances | `data/personal.db` (source of truth, pre-consolidation) | `sqlite3 ~/.hermes/data/personal.db ".tables"` |
| Story-like lessons learned | `state/narrative_memory.json` | `cat ~/.hermes/state/narrative_memory.json \| python3 -m json.tool` |
| What strategies worked/failed | `capsules/outcomes.jsonl` | `cat ~/.hermes/capsules/outcomes.jsonl \| tail -10` |
| Past failure patterns (reflexions) | `reflexion_memory.jsonl` | `cat ~/.hermes/reflexion_memory.jsonl \| tail -10` |
| Learned work patterns & preferences | `state/personal_model.json` | `cat ~/.hermes/state/personal_model.json` |
| Entities (people, companies, topics) | `entities.db` (legacy 0-byte stub, data now in unified_memory.db) | Query `hermes_entities` MCP tool instead |
| Curiosity findings (per-day log) | `journal/curiosity-YYYY-MM-DD.md` | Read from this repo's `journal/` directory |
| Session journals | `journal/YYYY-MM-DD.md` | Read from this repo's `journal/` directory |
| Who Relay is, standing instructions | `memory/relay.md`, `standing-prefix.md` | Read from this repo |

## Store consolidation status

As of 2026-08-10, all 8 legacy memory stores have been consolidated (read-only migration) into **unified_memory.db** via `hermes_consolidate.py`. Source DBs are preserved as the source of truth but should be considered legacy — new writes go dual-write to claudemem + unified via the `hermes-memory-mcp` server.

## Removed infrastructure (2026-08-10)

- **Qdrant** (vector DB, port 6333/6334) — removed. Was used by OpenWebUI; Synapse uses `SYNAPSE_EMBED_PROVIDER=local` (hash embeddings) and does not depend on Qdrant.
- **MenteDB** (cognitive memory graph, port 6677) — removed per user request. The `mentedb:fixed` container and its bind-mount data at `/home/rohit/services/mentedb/data` are deleted. No active service depends on it.

## Notes
- **unified_memory.db (85.6 MB)** is the consolidated brain. Populated by `hermes_consolidate.py` (run nightly at 2AM by `backup_all.sh` before kopia + off-site brain sync).
- The MCP memory server (`hermes-memory-mcp`, ~8091) exposes `hermes_entities`, `hermes_shared_facts`, `hermes_recall`, `hermes_save_observation` — all pointed at unified_memory.db.
- The MCP gateway runs at `http://mcp-gateway:8090`.
