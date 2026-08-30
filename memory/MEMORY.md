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
