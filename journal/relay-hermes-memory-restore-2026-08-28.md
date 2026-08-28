---
created: 2026-08-28
confidence: high
source: deep-dive recovery
---

# Hermes Memory Restored (2026-08-28)

## Problem
Rohit reported "all my memory lost". Hermes in the Telegram group greeted him as
if a stranger with no profile, no memory of months of work.

## Root cause
The docker-compose mount `~/.hermes:/opt/data` resolves to **`/root/.hermes`**
(because `docker compose` runs as root), NOT `/home/rohit/.hermes`. When the
container was recreated Aug 26/27 (to fix the bind mount), it pointed at a
BRAND-NEW empty `/root/.hermes`, so the container ran for ~a day on fresh,
empty data. The months of accumulated memory sat untouched in
`/home/rohit/.hermes` (631MB).

## Recovery performed
1. Snapshot current working dir: `/root/.hermes-current-pre-recovery-20260828.tar.gz`
2. `rsync -a` merged old content from `/home/rohit/.hermes/` → `/root/.hermes/`,
   EXCLUDING the working `config.yaml` and `.env` (the Telegram LLM fix).
3. Fixed ownership: `chown -R hermes:hermes /opt/data` (uid 10000) — the restore
   had left some files owned by host uid 1000, causing
   `PermissionError: /opt/data/logs/agent.log`.
4. **state.db was corrupted** by a stale WAL from the fresh instance replaying
   against the restored 3MB DB. Fixed: stopped container, removed
   `state.db{,-wal,-shm}`, copied the clean 3MB source `state.db` back in,
   restarted. Result: `integrity: ok`, **22 sessions** restored.

## Verified while gateway running
- Gateway: running, TG: connected
- unified_memory.db (89MB): ok
- hermes_memory.db: ok
- state.db: ok (22 sessions)
- temporal_kg.db: ok
- kanban.db: ok
- 8 SOUL persona files present
- Working model config preserved: agentharness-proxy (custom, localhost:8080)

## Root-cause fix (STILL PENDING)
The compose mount `~/.hermes:/opt/data` is fragile because `~` = root when
compose runs as root. Recommend changing the compose mount to the ABSOLUTE path
`/home/rohit/.hermes:/opt/data` so the container always reads the real data dir.
NOT done yet — needs a compose edit + container recreate (risky, do carefully).

## Pre-existing issues (unchanged)
- sentinel-agent hook: `No such file: /opt/data/.hermes/hermes-agent`
- AgentHarness proxy stability (cloud providers exhausted)

## Lesson
Never copy a SQLite DB into a data dir while a stale `-wal`/`-shm` from a
different (smaller/schema-different) DB is present — it corrupts the new file.
Always stop the consumer, remove stale journal files, then copy the clean DB.
