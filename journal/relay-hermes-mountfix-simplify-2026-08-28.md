---
created: 2026-08-28
confidence: high
tags: [hermes, memory, mount, simplification, cleanup]
---

# Hermes Memory Restored + Simplification (2026-08-28)

Follows session journal `relay-hermes-memory-restore-2026-08-28.md`. This covers
the root-cause mount fix and the consolidation work.

## Permanent mount fix (DONE)
Root cause of "memory lost": compose `~/.hermes:/opt/data` resolved `~` to
`/root` (compose runs as root), so the recreated container read a fresh empty
`/root/.hermes` instead of the real `/home/rohit/.hermes`.

Fix: changed BOTH service mounts (gateway + dashboard) in `/home/rohit/docker-compose.yml`
from `~/.hermes:/opt/data` to the ABSOLUTE path `/home/rohit/.hermes:/opt/data`.
Verified `docker inspect hermes` shows `/home/rohit/.hermes -> /opt/data`.
This can never silently revert now. Backup: `docker-compose.yml.bak-mountfix`.

## state.db corruption fixed
The restored 3MB state.db got corrupted by a stale WAL from the fresh small
instance replaying during startup. Fixed by stop → remove `state.db{,-wal,-shm}`
→ copy clean source `state.db` → start. Verified `integrity: ok`, 22 sessions.

## Canonical data dir is now /home/rohit/.hermes
Container reads and writes `/home/rohit/.hermes` directly. `/root/.hermes` is the
legacy copy (safety snapshots: `hermes-home-pre-mountfix-20260828.tar.gz`,
`hermes-current-pre-recovery-20260828.tar.gz`).

## Simplification Tier 1: code/data split (DONE)
- IMPORTANT: `collaborator-memory/` is LIVE — Hermes itself reads it as its
  memory index (`cd ~/.hermes/collaborator-memory && git pull`, reads
  `memory/MEMORY.md`, `memory/relay.md`, `journal/*`). DO NOT move it.
- Moved inert nested source repo `hermes-agent/` (204MB, only used by the manual
  `hermes update` command, NOT by the running gateway) out of the data dir to
  `/home/rohit/homelab/code/hermes-agent`, left a symlink so any path resolves.
  Data dir went 631MB → 457MB.

## Simplification Tier 3: container audit (DONE)
- Memory said "60+ containers" — OUTDATED. Current REALITY: **23 running
  containers**, all healthy and in use, managed by `/home/rohit/services/docker/compose/apps.yml`
  + `/home/rohit/docker-compose.yml`, plus standalone `ollama`.
- No idle/dead containers to stop; container RAM ~4-5GB of 62GB — well in budget.
- Removed ONE empty dangling volume `relay_hermes-data` (empty, unreferenced).
- Corrected stale "60+ containers" note in `memory/rohit.md` → "23 running".

## Verifications (all green)
- Gateway: running, TG: connected
- Memory DBs: state.db, unified_memory.db, hermes_memory.db all `integrity: ok`
- PiHole: doubleclick.net→0.0.0.0 (blocked), google.com resolves
- Load 0.15, 50GB RAM available, disk 69% (66G free)

## NOT done (per user)
- Tier 2 (AgentHarness proxy → direct LLM refactor) — deliberately skipped.
