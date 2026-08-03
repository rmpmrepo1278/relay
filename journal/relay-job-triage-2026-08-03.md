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

## Commits
- `001febd` on chaguli (AgentChaguli, master): scheduler --once, tracker RETIRED_JOBS, hesclate, telegram-notify hook, bridge auth+subsystems. Pushed.
- `ec205b8` on chaguli: seed_memory.py (memory store population). Pushed.
- Collaborator memory journal synced after this note.

## Follow-ups
- Next scheduled boot_inbox_watcher run (monthly) should show success — confirm on next report.
- Bridge smoke test completed for all 28 commands (post-seed); `/memory` now returns matches.
- Suggest wiring temporal KG (48k facts) into `search` as fallback so entity facts are reachable via /memory, in addition to seed_memory.md docs.
