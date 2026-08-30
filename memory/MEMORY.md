# Memory Index

## The Person
- [rohit.md](rohit.md) — who Rohit is, how he works, what matters to him
- [homelab-infrastructure.md](homelab-infrastructure.md) — the homelab stack
- [hermes-architecture.md](hermes-architecture.md) — Hermes agent architecture and state
- [vision.md](vision.md) — what Rohit wants to build

## The Collaborator
- [relay.md](relay.md) — who Relay is
- [grants.md](grants.md) — standing permissions → ../grants.md
- [tempo.md](tempo.md) — calibration data → ../tempo.md
- [seedline.md](seedline.md) — version vector → ../seedline.md
- [ideas.md](ideas.md) — current ideas → ../ideas.md

## The Homelab's Backend Stores
- [databases.md](databases.md) — index of all 17+ DBs, what each contains, and how to query them
- [benchmarks/](benchmarks/) — canonical LLM benchmark store (tok/s, tool-call latency, load times), versioned; add runs via `bin/bench_llm.py`

## Decisions
- [minipc.md](minipc.md) — mini-PC augment purchase decision (recommendation: BOSGAME M6 $969)
- [ram-upgrade.md](ram-upgrade.md) — home-hp 32GB→64GB RAM decision (recommendation: Rimlance 32GB $158 Newegg)

## How to read this memory

This repo is the **thin index layer** — human-readable context and cross-tool continuity.
For detailed data (chat history, facts, narratives, capsule outcomes, preferences),
query the canonical backend stores listed in [databases.md](databases.md).

Loaded at session start during initialization. Sync first, then read this index.


## Career-Ops Automation
`projects/career-ops/` — batch career-run automation. Google Sheets `Jobs` tab is
the queue; n8n polls every 15m → bridge `/run` at `172.18.0.1:9199` (docker-bridge
only, LAN-locked) → `career_launch.sh` → `auto_pipeline.py` (deterministic ATS
keyword coverage via `_compute_ats_keyword_match`) → results written back to the
sheet row + posted to Telegram topic 7338, recorded in
`career_batch_results.tsv`. Phone trigger: paste a job URL or `/job <url>` in
topic 7338 → `career_ops_pipeline` Hermes plugin SSH-executes `auto_pipeline.py`
on the host. (Two triggers, separate dedup — avoid submitting the same URL both
ways.) Bridge service: `n8n-bridge.service` (ExecStart=/usr/bin/python3,
N8N_BRIDGE_HOST=172.18.0.1).

### 2026-08-30: bridge auth + Jarvis memory persistence

- **Bearer gate (defense-in-depth):** `/run`, `/cmd`, `/docker-*`, `/service-*`,
  `/run-cron` are now **bearer-mandatory** even from trusted/private IPs
  (`SENSITIVE_PATHS` in `n8n_bridge_server.py`). n8n workflow `/run` nodes send
  `Authorization: Bearer {{ $vars.BRIDGE_AUTH_KEY }}` (n8n project var; NOT hard-coded
  in the committed JSON). **n8n won't run until you create the n8n project variable
  `BRIDGE_AUTH_KEY` = `d6cbba9e9e3f09dcfb545c7ae0521ba5191407a7bb0bfcc401eeba1753001549`**
  (matches the unit env). Telegram `/run` routes in-process (`_call` → `HANDLERS`),
  unaffected. Verified: no-bearer `/run`=401, with-bearer=200.
- **Jarvis → Hermes memory persistence:** new bridge `/memory-write` (trust-gated,
  bind to docker bridge; runs `unified_memory.py store` as root via `sudo -n` with
  `HOME=/home/rohit`), and `openjarvis/tools.py` `_persist_reply()` POSTs each
  Jarvis reply to it. GateWay restart needed: `docker restart hermes` (s6-supervised).
  `hermes tools list` confirms `✓ openjarvis 🔌`. Jarvis runs `jarvis serve`
  @127.0.0.1:1377.
- **⚠️ OWNERSHIP MODEL (critical):** the hermes container (`stage2-hook.sh`) chowns
  the entire host `/home/rohit/.hermes` tree to uid **10000 mode 700** on every boot,
  which blocks the rohit-run bridge. Mitigations applied:
  - `plugins/`, `platforms/`, `.local/state/hermes`, `kanban*`, `kanban/` → uid 10000
    (gateway-owned). `data/unified_memory.db` + `data/career_batch_results.tsv` stay
    `rohit` (rohit-writable; memory-write uses `sudo -n` root so DB ownership is moot).
  - `n8n-bridge.service` now has `ExecStartPre=/usr/bin/sudo -n chmod 705
    /home/rohit/.hermes` (re-grants rohit traverse after container chowns) and
    `EnvironmentFile=/home/rohit/.relay/bridge.env` (copy of `.hermes/.env` — the
    container chowns `.env` to 10000:600 so the bridge reads the relocated copy).
  - If kanban fails after a container restart: re-chown `kanban.db*` files to 10000
    and remove stale 0-byte `-wal`/`-shm`.
  - **Do NOT restart the hermes container casually**: each boot re-chowns `.hermes`
    to 10000:700; the bridge's ExecStartPre self-heals on its next start, but other
    rohit-accessed files may need re-chowning.
