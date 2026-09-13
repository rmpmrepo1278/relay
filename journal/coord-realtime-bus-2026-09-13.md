# Real-time coordination: AgentBus adopted (redis-coord retired)

**Date:** 2026-09-13
**Status:** live — unified

Two agents independently built real-time buses in the same hour (the very
overlap the coordination layer exists to prevent, now noted):

1. **AgentBus (chosen standard)** — built by the Rohits-Air opencode session.
   Stdlib-only HTTP + SSE service on the homelab, systemd user unit
   `agentbus.service`, reachable at http://100.122.58.40:9107 over Tailscale.
   File-backed JSON (no password, survives restarts). Integrated into
   `bin/collaborator` (say / presence / claim / done / heartbeat / goal / bus).
   Verified Mac->homelab roundtrip; presence shows both agents; objectives
   registry seeded. Commits f3df210 / 48b0096 / 974bbf0.

2. **redis-coord (retired)** — built in parallel by the DSH session (Redis
   Streams on db2 via `docker exec`, mirror unit, docs). Fully working but a
   redundant duplicate; stopped the mirror unit, removed the files, and
   migrated the objectives into the shared AgentBus registry so there is ONE
   live channel and ONE objective registry for all agents.

Unified objective registry (7): homelab-opt, memory-sync, telegram-ux-parity
(in_progress), backups-reliable, career-ops, trivy-upgrade (open),
hermes-mind-stability (done).

Protocol for every agent: `collaborator say CHANNEL MSG` to publish,
`collaborator presence` to heartbeat, `collaborator goal list|add|status` for
shared objectives, `collaborator bus listen` to stream live. Durable history
still in git (state/coordination.json); the bus is the fast channel.
