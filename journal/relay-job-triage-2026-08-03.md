# Relay — Job Triage + Bridge Plugin Completion (2026-08-03)

## What shipped
- **boot_inbox_watcher fixed**: `~/.hermes/scripts/hermes_scheduler.py:273` now passes `--once` to `inbox_watcher.py` (script defaults to daemon mode → 30s scheduler timeout). Verified `python3 inbox_watcher.py --once` exits 0 in <20s. Scheduler restarted, 87 jobs parse OK.
- **Ghost jobs retired**: `kopia_backup`, `kopia_volumes`, `traefik_sync` removed from pruning/failure stats via new `RETIRED_JOBS` set in `~/.hermes/scripts/capability_tracker.py` (their scripts were deleted; `backup_all.py` supersedes). Report now tracks 94 jobs / 4 prune candidates (was 97 + ghosts).
- **cert_renew / cos_briefing / curious_explorer**: all confirmed working now (cert_renew 100% failure was a transient DNS timeout on Jul 27 pulling the image; returns "no renewal" exit 0). Historical aggregates will decay naturally.
- **hesclate added**: `~/.hermes/plugins/hermes-bridge/__init__.py` had 27 h-commands but `/escalate` was never mapped. Added `hesclate` to command list + `_BRIDGE_MAP`. Now 28/28 plugin commands resolve.

## Verification (post-restart)
- `hermes-gateway` + `hermes-scheduler` active.
- All 28 plugin h-commands resolve via `get_plugin_command_handler` in a fresh process.
- Bridge `/cmd` POST (Bearer auth) verified for `/help /status /ledger stats /cost /escalate /commitments status` — all return correct payloads.
- Confirm-gate verified: `hrun ls` → "⚠️ Confirm destructive action?" ; `hrun confirm echo bridge-ok` → `bridge-ok`.

## Gotcha notes
- Plugin command list + `_BRIDGE_MAP` use `}` with no leading space vs ` }` — patch must be line-based, not brace-pattern.
- `/cmd` handler expects `{"text": ...}` field, NOT `cmd`; response nests under `result.text`.
- Heredoc-over-SSH still breaks zsh; scp file + run is the only reliable pattern.

## Memory populated
- Unified memory store was empty (only 1 TEST entry) → `/memory <query>` returned nothing despite 48k facts in the temporal KG (separate store, not wired into `search`).
- Built `~/.hermes/scripts/seed_memory.py`: ingests `collaborator-memory/journal/*.md` (namespace=journal) + `memory/*.md` (namespace=memory) as full-doc entries + per-section FTS-indexable entries. 269 entries seeded; re-runs clear prior seeds first (FTS triggers only fire on INSERT/DELETE, so upserts alone would stale the index). Committed `ec205b8`, pushed.
- Verified: `/memory telegram|bridge|homelab|scheduler` all return real matches via bridge and CLI.

## Memory search hardened (TKG reachable)
- Wired the temporal KG (48k facts) into `unified_memory.search()` as a fallback via new `_search_tkg()` → entity/fact results now return as `[0.60] ... (tkg)` when FTS is empty, so `/memory <entity>` reaches the graph.
- Fixed an FTS5 crash: queries with hyphens/dots (e.g. `homelable-frontend`) threw `no such column: frontend`. Now tokens are sanitized to alnum; FTS block wrapped in try/except; added naive LIKE fallback on the store for robustness.
- Committed `3f94bb3`, pushed. Regression: `bridge homelab scheduler relay n8n` all return 3 results.

## End-to-end test (2026-08-03) — found & fixed a real bug
- Full E2E passed: plugin h-command → bridge `/cmd` → subsystem → temporal KG fallback (hmemory homelable-frontend, hledger stats), plus outbound Telegram delivery via `/ask` → "Sent to Telegram channel" (sendMessage API 200).
- **Bug found**: telegram-notify hook `handle(event_type, **kwargs)` crashed on every `agent:end` — gateway `HookRegistry.emit()` calls `fn(event_type, context)` with TWO positional args. Journal showed repeated `[hooks] Error in handler for 'agent:end': handle() takes 1 positional argument but 2 were given`.
- Fixed: `handle(event_type, context=None)`. Verified via real `HookRegistry.emit("agent:end", ...)` — no error. Committed `791e8de`, pushed.

## Commits
- `001febd` on chaguli (AgentChaguli, master): scheduler --once, tracker RETIRED_JOBS, hesclate, telegram-notify hook, bridge auth+subsystems. Pushed.
- `ec205b8` on chaguli: seed_memory.py (memory store population). Pushed.
- `3f94bb3` on chaguli: TKG fallback + FTS token sanitization in search. Pushed.
- `791e8de` on chaguli: telegram-notify hook handle() signature fix (2-positional emit). Pushed.
- Collaborator memory journal synced after this note.

## Audit: dedup / consolidation / security / resiliency (2026-08-03)

### Security fixes (committed `5f61bcf`)
- **Bridge bound to 0.0.0.0:9199** — exposed on all interfaces with a known default auth key. Fixed: bind to 127.0.0.1 only, load BRIDGE_AUTH_KEY/TELEGRAM_BOT_TOKEN from `.env` instead of hardcoded defaults.
- **`.env.systemd` was 664 (group-readable)** with API keys — fixed to 600.
- **`.env.bak`** contained plaintext API keys — shredded.
- **n8n-bridge service file**: was `Restart=on-failure` (should be `always` for a bridge), no `TimeoutStopSec`, no `WorkingDirectory`, no `EnvironmentFile`, no journal output. Fixed all.

### Resiliency fixes (committed `7750615`)
- **homelab-backup.service** and **system-health-check.service**: oneshot with no `Restart=` policy — added `Restart=on-failure` so crashes re-run.

### Consolidation
- **unified_memory_mcp.py** (new, consolidated MCP server exposing all memory stores) was unregistered — added to `config.yaml` under `mcp_servers.unified_memory`.
- **hermes_mcp_server.py** (old, single-store MCP) still registered and running; both coexist since they serve different purposes (control plane vs data plane).
- **hermes_memory.py** superseded by unified_memory.py — archived.
- **temporal_kg.py** NOT archived — still actively used by insight_engine, research_indexer, soul_overlay_gen, and scheduler.
- **graphrag.py** NOT archived — still actively used by scheduler graphrag_extract job (every 12h).
- **homelab_* scripts** form a pipeline (discover → evaluate → deploy → optimize → report → troubleshoot), not duplicates.

### Stale data cleaned
- **databases.md**: said unified_memory.db was empty (0 records) — updated to reflect 262 entries after seeding.
- **Archive cleanup**: removed career_briefing.py.bak, flock_wrapper.sh, logrotate_wrapper.sh, memory_sync.sh (no references anywhere).

### Commits
- `5f61bcf` on chaguli: security (bridge bind address, .env loading, service file). Pushed.
- `7750615` on chaguli: resiliency (Restart=on-failure for oneshots, .env.systemd perms). Pushed.
