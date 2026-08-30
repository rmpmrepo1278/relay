# Relay session — 2026-08-30: bridge bearer auth + Jarvis memory persistence + ownership incident

## What was asked
Complete the career-ops hardening + persistence recommendations ("do all"):
1. bridge `/memory-write` (write Hermes memory for Jarvis replies)
2. bearer gate on `/run`,`/cmd`,`/docker-*`
3. patch `openjarvis/tools.py` to persist replies
4. CRG watch on `projects/hermelab` (skipped — dir doesn't exist; no such repo)
5. `graphify` restore (skipped — opencode skill only, no CLI)

## Done + verified
- Bridge `n8n_bridge_server.py`:
  - `SENSITIVE_PATHS` → bearer-mandatory for `/run`,`/cmd`,`/docker-*`,`/service-*`,`/run-cron`
    even from trusted/private IPs. `check_auth(path)` path-aware. Verified:
    no-bearer `/run`=401, with-bearer=200, non-sensitive `/ping`=200.
  - `/memory-write` handler: runs `unified_memory.py store` as root via
    `sudo -n env HOME=/home/rohit` (root bypasses container-owned `.hermes` mode).
    Verified stored + search readback.
- `n8n-bridge.service`: added `BRIDGE_AUTH_KEY` (unit env)
  `d6cbba9e9e3f09dcfb545c7ae0521ba5191407a7bb0bfcc401eeba1753001549`,
  `ExecStartPre` re-chmods `.hermes` to 705 (rohit traverse), `EnvironmentFile`
  → `/home/rohit/.relay/bridge.env`. n8n workflow `/run` nodes send
  `Bearer {{ $vars.BRIDGE_AUTH_KEY }}` (committed `8faa28c`, no secret in git).
  **User action: create n8n project variable `BRIDGE_AUTH_KEY` = the key above.**
- `openjarvis/tools.py`: `_persist_reply()` POSTs each Jarvis reply to
  `/memory-write` (best-effort, swallowed on failure). py_compile OK.
- Gateway restarted (`docker restart hermes`); `hermes tools list` → `✓ openjarvis 🔌`;

## Incident: `.hermes` ownership churn
Restarting the hermes container triggered its `stage2-hook.sh` which chowns the
whole host `/home/rohit/.hermes` tree to uid 10000:700, which broke:
- rohit bridge (couldn't read `.hermes/.env`, script, or use cwd → wouldn't start)
- gateway plugin discovery, telegram locks, kanban DB, pairing (partial chown)

Fixed by (targeted, kept `unified_memory.db` + `career_batch_results.tsv` on rohit):
- plugins/platforms/.local-state/hermes/kanban* → 10000 (gateway-owned)
- `.hermes` root → 705 traverse for rohit (self-heals via bridge ExecStartPre)
- removed stale 0-byte `kanban.db-wal`/`-shm` (SQLite sidecars can't cross owners)
- `.env` relocated copy → `/home/rohit/.relay/bridge.env` (container chowns `.env`)

All green: gateway up, kanban 0 failures, Jarvis :1377=200, openjarvis enabled,
bridge active, bearer 401/200, memory-write stored.

## Residual friction / follow-ups
- Every hermes container restart re-chowns `.hermes` → do NOT restart casually;
  bridge self-heals on next start, but other rohit-deps may need re-chown.
- n8n workflow now requires the `BRIDGE_AUTH_KEY` project var (set it or automation 401s).
- `hermes-mind-loop.service` (user unit) was already `failed` — pre-existing, unflagged.