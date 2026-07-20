# Unified Memory Layer - Design

## Goal
One memory source that all three tools (opencode, Claude Code, Hermes) read/write via MCP,
consolidating Hermes fragmented stores without losing any functionality.

## Audited state
- Hermes: persistent structured stores - claudemem.db, temporal_kg.db, shared_facts.db,
  kanban.db, state.db, hermes_memory.db, reflexion_memory.jsonl, collaborator-memory (git).
- Claude Code: session transcript + project checkpoints + HERMES_MEMORY.md injected at startup.
  One-way (Hermes -> Claude Code). No write-back.
- opencode: stateless executor - config only, no memory.

## Gaps
- opencode <-> Hermes: none.
- Claude Code -> Hermes: none (no write-back).
- Cross-session continuity: only Hermes has it.

## Decision: single Unified Memory MCP server
unified_memory_mcp.py (stdio) fronts ALL stores behind 4 tools:
- memory_query(store, query, limit) - SQL/search across stores
- memory_store(store, data) - write (observations, facts, KG capsules, goals, tasks, collab notes)
- memory_recall(topic) - cross-store recall
- memory_stats() - store sizes

All three tools connect to THIS server. Hermes remains the backing-store owner; the server is the
canonical access layer. Cross-tool memory achieved because every tool talks to the same source.

## Integration
- opencode: ~/.config/opencode/mcp.json -> mcpServers.unified-memory (stdio)  [DONE]
- Claude Code: ~/.claude.json -> mcpServers.unified-memory (stdio)           [DONE]
- Hermes: adopt unified_memory.py client incrementally                         [in progress]

## Consolidation
Replaces per-tool / ad-hoc memory access with one interface. Preserves all capabilities
(claudemem FTS, KG queries, shared facts, kanban, reflexion, collab).

## Migration (incremental, low-risk)
Hermes internal scripts may keep using DBs directly (safe). New code should import the
unified_memory client. Full rewrite of ingestion (conversation_processor, mind_loop) is
DEFERRED to avoid disrupting the production homelab.
