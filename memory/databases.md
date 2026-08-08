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
| Recent sessions, chat history | `state.db` (134 MB) | `sqlite3 ~/.hermes/state.db "SELECT * FROM messages ORDER BY id DESC LIMIT 10;"` |
| Observed facts, SOPs, compressed memories | `claudemem.db` (6.1 MB) | `sqlite3 ~/.hermes/claudemem.db "SELECT * FROM observations ORDER BY id DESC LIMIT 10;"` |
| Temporal facts about entities/services | `temporal_kg.db` (4.7 MB) | `python3 ~/.hermes/scripts/temporal_kg.py query "paperless failures"` |
| Semantic relationships (nodes + edges) | `knowledge_graph/graph.db` (164 KB) | `sqlite3 ~/.hermes/knowledge_graph/graph.db "SELECT * FROM kg_nodes;"` |
| Story-like lessons learned | `state/narrative_memory.json` (20 KB) | `cat ~/.hermes/state/narrative_memory.json \| python3 -m json.tool` |
| What strategies worked/failed | `capsules/outcomes.jsonl` (35 KB) | `cat ~/.hermes/capsules/outcomes.jsonl \| tail -10` |
| Past failure patterns (87 entries) | `reflexion_memory.jsonl` (24 KB) | `cat ~/.hermes/reflexion_memory.jsonl \| tail -10` |
| Learned work patterns & preferences | `state/personal_model.json` (2.3 KB) | `cat ~/.hermes/state/personal_model.json` |
| Shared facts (goals, preferences, context) | `shared_facts.db` (56 KB) | `sqlite3 ~/.hermes/shared_facts.db "SELECT * FROM shared_facts;"` |
| Decision register | `data/decisions.db` (52 KB) | `sqlite3 ~/.hermes/data/decisions.db "SELECT * FROM decisions;"` |
| Habits, projects, health, finances | `data/personal.db` (80 KB) | `sqlite3 ~/.hermes/data/personal.db ".tables"` |
| Entities (people, companies, topics) | `entities.db` (36 KB) | `sqlite3 ~/.hermes/entities.db "SELECT * FROM entities;"` |
| Curiosity findings (per-day log) | `journal/curiosity-YYYY-MM-DD.md` | Read from this repo's `journal/` directory |
| Session journals | `journal/YYYY-MM-DD.md` | Read from this repo's `journal/` directory |
| Who Relay is, standing instructions | `memory/relay.md`, `standing-prefix.md` | Read from this repo |

## Notes
<<<<<<< Updated upstream
- **unified_memory.db** (68 KB) exists but is empty (0 records) — may be used in future.
- **MenteDB** (cognitive memory graph at port 6677) is **online** — run as `mentedb:fixed` container (NOT the broken upstream `ghcr.io/nambok/mentedb:latest`, which crashes instantly: binary needs GLIBC_2.39 but image ships GLIBC 2.36). Healthy at `http://localhost:6677/v1/health`. Data persists at `/home/rohit/services/mentedb/data`. Fix documented in `journal/relay-mentedb-fix-2026-08-06.md`.
=======
- **unified_memory.db (937 KB, 262 entries after seed_memory.py populate) — may be used in future.
- **MenteDB** (cognitive memory graph at port 6677) is currently offline.
>>>>>>> Stashed changes
- The MCP memory server runs at `http://192.168.29.10:8091/mcp` for tool-based queries.
