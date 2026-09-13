# Real-time coordination bus deployed (coord)

**Date:** 2026-09-13
**Status:** live

Built `bin/coord`: Redis-Streams (db2) bus for real-time agent-to-agent comms
between the DSH session (homelab-side) and the Rohits-Air opencode session, and
any future agents. Redis was chosen because it is already running
(redis:7-alpine, healthy), db2 is free, and `docker exec redis redis-cli -n 2`
requires no port exposure, no compose change, and no new service.

Components:
- `bin/coord` — say / listen / status / ping / partners / objective subcommands
- `agent-coord-mirror.service` (systemd --user, enabled, running) — durable
  mirror: every event -> `state/inbox/<date>.log` (git-backed)
- `state/objectives.json` — shared objective registry (seeded: telegram-ux
  parked, hermes-mind-stability done, backups-reliable, career-ops, trivy-upgrade)
- `docs/coord-realtime.md` — full protocol + failure modes

Verified live: publish -> listener delivery <2s, cursor resume, full-history
catch-up for new consumers, presence (ping/partners), mirror capture, objective
set broadcasting a bus event.
