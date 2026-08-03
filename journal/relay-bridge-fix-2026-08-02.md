# Relay session: code-review-bridge repair + cleanup completion (2026-08-02)

## code-review-bridge (port 8096) — FULLY REPAIRED
Root causes found & fixed in `agentharness/merged-mcp/code-review-bridge/`:
1. Container relied on host pipx venv whose symlinks break inside Docker → now `pip install code-review-graph` in the image.
2. Tool names sent with underscores (`dead_code`) but CLI wants hyphens (`dead-code`) → `replace("_","-")`.
3. `CRG_PYTHON` pointed at nonexistent `/usr/local/bin/python3.13` → dropped, calls `/usr/local/bin/code-review-graph`.
4. Broken pipx symlink at `/home/rohit/.local/bin/code-review-graph` shadowed the container binary → removed PATH prepend, use absolute path.
5. Broad `/home/rohit:ro` mount made graph.db read-only → WAL open failed; added overriding rw mount `/home/rohit/.code-review-graph`.
6. Gateway health probe (GET /health) got 501 → added `do_GET` returning 200.
7. Per-tool `--data-dir` unsupported by most subcommands → dropped; CLI auto-detects DB from repo root now.

Verified: architecture (15 communities), dead-code (84 items, down from 105), repos all return data. Gateway registry reset to healthy (was 437 consecutive failures).

## MenteDB alert — DISABLED
Found n8n workflow "MenteDB Health Check" (id VBjlmcMFzOwmmyIR) in SQLite via `node sqlite3`. Set active=0. Source of the historical MenteDB telegram alert.

## Graph refresh
`code-review-graph update --skip-flows`: 273 files updated, FTS rebuilt (1131 rows).

## Repos pushed
- home (AgentChaguli): 77a02c9 chore remove dead/archived scripts (45 archive files + 7 non-exec modules deleted)
- agentharness (AgentHarness): d4107dc bridge fix (earlier 2ddea17)
- collaborator-memory: clean

## Environment note
Tailscale client logged out on Mac; used `homelab-lan` (192.168.29.10) fallback for SSH all session.
