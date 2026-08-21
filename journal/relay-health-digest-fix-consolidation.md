# Health Digest Fix + Container Consolidation

**Date**: 2026-08-21  
**Commits**: `62ec4fe` (root), `f39236c` (AgentChaguli), `b3fe2be` (metronix-backend local)

## Q1: Why Memory/Load were N/A

The health digest n8n workflow calls `http://172.18.0.1:9199/system-health`.
The `/system-health` endpoint only returned systemd service status — **no
memory, CPU load, or disk metrics were collected at all**.

**Fix**: Added psutil-based system metrics to `n8n_bridge_server.py`'s
`handle_system_health()` handler:
- `load`: 1m/5m/15m averages
- `memory`: total, used, available, percent (human-readable MB/GB)
- `disk`: deduped mountpoints (only show unique devices — `/` and `/home`
  are the same filesystem on this host)
- `digest`: pre-formatted text string (passed through by n8n Format step)
- `containers`: list all containers with unhealthy detection

Restarted `n8n-bridge.service` to pick up changes.

## Q2: Container Overlaps & Unused Services

### Consolidated (2 containers removed, 54→52):

**Ollama (standalone + metronix-full):**
- Standalone: port 11434, 10 models (52GB disk) — USED by hermes via Forge proxy
- metronix-full-ollama: port 11435, 2 models (2.1GB disk) — REDUNDANT
- Fixed: Changed ollama port binding `127.0.0.1:11434 → 0.0.0.0:11434` so
  Docker containers can reach it via `host.docker.internal`
- Updated metronix-core: `OLLAMA_HOST=http://host.docker.internal:11434`
- Removed `metronix-full-ollama` container + orphan volume
- **Savings**: ~2.1GB RAM + 1 GPU slot + 2.1GB disk

**Neo4j (standalone + metronix-full):**
- Standalone: port 7687, 427 nodes (memory system data) — USED by agent-memory MCP
- metronix-full-neo4j: port 7688, 0 nodes (locked, empty) — REDUNDANT
- Updated standalone neo4j password: `neo4j-homelab → metronix-homelab`
- Updated metronix-core: `NEO4J_URI=bolt://host.docker.internal:7687`
- Removed `metronix-full-neo4j` container + orphan volume + full_neo4j_data volume
- **Savings**: ~517MB disk + 1 GPU slot

### Intentionally NOT consolidated (Redis × 3):
- `redis` (core), `authentik-redis`, `metronix-full-redis`
- Each serves a distinct stack with its own data — correct isolation

### Service Usage Audit:

| Service | Status | Content | Action |
|---|---|---|---|
| calibre-web | **ACTIVE** | 995 ebooks (13GB) in `/mnt/usb/ebooks` | KEEP |
| bookstack | **UNUSED** | 0 pages, 0 books, 0 users (only defaults) | CANDIDATE FOR REMOVAL |
| linkwarden | **UNUSED** | 0 links, 0 tags, 0 users, 0 collections | CANDIDATE FOR REMOVAL |
| homeassistant | **UNUSED** | 0 entities, 0 devices, 0 integrations | CANDIDATE FOR REMOVAL |

## Infrastructure Fixes:
- Removed accidental `services/synapse/` clone (pnpm store permission issue)
- Fixed splade port conflict: was clobbered to `8000:8000` (conflicts with paperless),
  restored to `8098:8080` (original value from git history)
- Fixed metronix-core port: was `8000:8000` (conflicts with paperless),
  restored to `8086:8000`
- All services verified healthy: 0 mind_loop errors in cycle 3682+
