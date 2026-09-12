---
name: code-graph-query
description: "Query the code dependency graph -- find callers, dead code, impact analysis, architecture, and semantic search."
---

# Code Graph Query

Query the code-review-graph via the n8n bridge server (port 9199) for code intelligence.

## Endpoints (via bridge)

All queries go to `http://127.0.0.1:9199/code-graph/<endpoint>`:

| Endpoint | Method | Body | Returns |
|----------|--------|------|---------|
| /code-graph/status | GET | -- | Graph stats (nodes, edges, files, languages) |
| /code-graph/dead-code | GET | -- | Unreachable functions/classes sorted by risk |
| /code-graph/query | POST | {"type":"<qtype>","target":"<name>"} | Callers/callees/hierarchy |
| /code-graph/search | POST | {"q":"<query>"} | Semantic + FTS search |
| /code-graph/impact | POST | {"files":"<csv>"} | Files affected by changes |
| /code-graph/architecture | GET | -- | Community structure, cohesion, layering |

## Query Types

- `callers_of` -- who calls a function/class
- `callees_of` -- what a function/class calls
- `hierarchy` -- class inheritance chain
- `dependents_of_file` -- files depending on a given file

## When to Use

- "How is X implemented?" -> `query` with `callers_of`
- "Is this function used?" -> `dead-code`
- "What breaks if I change X?" -> `impact`
- "Find code related to Y" -> `search` (semantic)
- Before refactors, PR reviews, bug investigation

## Repos Indexed

- **agentharness** (1737 nodes, 15559 edges, 189 files)
- **hermes-agent** (via daemon)

Graph auto-updates via `crg-daemon`.
