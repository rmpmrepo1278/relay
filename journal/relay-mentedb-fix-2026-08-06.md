# Relay Journal — 2026-08-06 — Telegram Exchange Review & MenteDB Fix

## Context

Reviewed the Telegram exchange (Aug 05–06). Three issues surfaced: repeated
"MenteDB is DOWN" alerts, a doctor false-positive on the collaborator-memory
code graph, and CoS briefing false alarms (LLM :18090, calendar).

## 1. MenteDB "DOWN" alerts — ROOT CAUSE FOUND (not memory!)

The prior agent response ("MenteDB is down due to excessive memory usage.
I've restarted it.") was **unverified and wrong** — no tool actually ran
(flagged ⚠️ Not verified), and "excessive memory usage" was fabricated.

Real cause: the published image `ghcr.io/nambok/mentedb:latest` is **broken**.
It is built on `debian:bookworm` (GLIBC 2.36) but the `mentedb-server` binary
requires GLIBC_2.39. Every container start crashed immediately:

```
mentedb-server: /lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.39' not found
```

So no restart could ever succeed. This is an upstream packaging bug, not a
runtime/resource problem.

### Fix (verified on homelab via homelab-lan)
1. Built corrected image `mentedb:fixed` from `debian:trixie-slim` (GLIBC 2.41),
   copying the `mentedb-server` binary from the upstream image.
   Dockerfile: `/home/rohit/services/mentedb/Dockerfile`.
2. Ran container:
   `docker run -d --name mentedb --restart unless-stopped -v /home/rohit/services/mentedb/data:/var/mentedb/data -p 6677:6677 -p 6678:6678 mentedb:fixed`
3. Verified: `docker ps` → Up; `curl localhost:6677/v1/health` →
   `{"status":"ok","uptime_seconds":4,"version":"0.1.0"}`.
4. Survives `docker restart`; RSS only ~183 MiB (contradicts the memory claim).

### Operational note
- Health endpoint is `/v1/health` (plain `/health` returns 404).
- Do NOT `docker pull`/watchtower the upstream `:latest` — it is broken.
  If the fixed image is lost, rebuild from `/home/rohit/services/mentedb/Dockerfile`.

## 2. Doctor "Graph stale/empty: collaborator-memory (0 nodes)"

False positive. `collaborator-memory` is a **markdown-only** docs repo — CRG
correctly produces 0 nodes. It was permanently flagged and its watcher rebuilt a
useless empty graph with log spam ("Removed: memory/databases.md" loop).

### Fix
- Removed `collaborator-memory` from `~/.code-review-graph/watch.toml`
  (backup: `watch.toml.bak`); it was already absent from `registry.json`.
- Killed its watcher process (pid 866142); daemon did not respawn it.
- `homelab_graph.crg_graph_health(stale_hours=48)` now returns `[]`.

## 3. CoS briefing false alarms (LLM :18090, calendar) — already fixed

Journal `relay-cos-briefing-false-alarms-2026-08-06.md` + commit `7eda9a7b3`
(Aug 05) already corrected `cos_briefing.py`: LLM health now checks `:8080`
(AgentHarness proxy, verified healthy: `{"status":"ok","type":"agentharness_proxy"}`)
and calendar reads the `calendar_intelligence.py` cache. No action needed.

## What was NOT touched
- Tailscale is offline on this Mac; used `homelab-lan` (192.168.29.10) — the
  Tailscale IP 100.122.58.40 is unreachable.

## Memory updates
- `memory/databases.md`: MenteDB marked **online**, with broken-image warning.
