# Autonomous agent conversion (Hermes-style persistent loops) — 2026-09-14

**Status: LIVE — all 8 domain agents run as autonomous systemd loops.**

## What changed
- New shared frame `agent_loop.py` (in code/scripts, mirror of ~/.hermes/agents/agent_loop.py):
  persistent loop, memory namespace (store.json + reflection.jsonl), playbook
  reader, LLM decision layer (hop gateway haiku-4.5 local, offline-safe
  deterministic fallback to `check`), domain-script-as-tool execution,
  reflection append, agentbus presence heartbeats.
- 8 systemd --user units `agent-<name>.service` (interval 300s, Restart=on-failure):
  baseplate, vault, courier, inference (DSH), finlay, housekeep, calendula,
  connector (wrapped from the deterministic scripts — scripts unchanged).
- Cron per-agent 04:45 checks REMOVED (loop owns sweeps now). Jenny 05:00 brief
  stays on cron; Jenny conversion is the other session's lane (memory/jenny.md
  authority work committed there).
- LLM decision layer verified: calendula/connector produce real reasoning
  ("scheduled health sweep", "daily scheduled check for upcoming birthdays...");
  malformed replies fall back safely. Overnight hop-free window exercised the
  deterministic fallback for ~6h with rc=0 — offline operation proven.

## Verification
- Regression 7/7 PASS (bridge, tg-send, docker-ps 24, autoheal, inventory 39,
  ask-func, gdrive-owned).
- All 8 units active running; loops cycle every ~5 min; reflection journals
  growing; board tasks stable.

## Open
- Jenny autonomous loop conversion: other session's lane (proposed).
- LLM decision quality: free fallback chain may throttle; parser hardened to
  tolerate free-text replies.