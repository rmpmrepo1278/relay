# Relay — Telegram Inbound Restore (bridge /jenny directive path)

## Symptom
User sent "hi" to the Telegram bot (topic 10000 → jenny); no reply since
~2026-09-18T04:10Z. Last successful directive `jenny-1789704627-49f68a`
(created 04:10:27Z, handled 04:10:30Z, replied 04:11:01Z). No new `owner=jenny`
tasks since; `state/telegram_offset.json` frozen at offset 814285830.

## Root cause
Two stacked failures in the bridge path:

1. **`/jenny` + topic-routing removed from the bridge source.** The agent-routing
   block (`_jenny_directive`, `_agent_cmd`, `agent_cmds` for `/homelab` `/personal`
   `/jenny`, and the `thread_id → agent` topic map with the plain-text fallthrough
   `current_agent`) was deleted by the collaborator-memory sync commit `fcdcc7c`
   (2026-09-18T01:03Z, "sync: collaborator memory update", -561/+220 lines). This
   was **unintentional drift**, not a design decision: the capability was built
   Sep 13-14 (journals), still referenced by the Sep 17 LLM-conversion journal,
   and the deployed bridge kept using the working code until replaced.
2. **Stale host bridge held 9199 with a dead poller.** A host process
   (pid 2508954, started Sep 17 21:29 local, cmdline `/opt/data/scripts/n8n_bridge_server.py`
   with `/opt/data` long since unmounted) sat on 127.0.0.1:9199 running** deleted
   code from memory; its getUpdates poller was stuck (SYN-SENT to api.telegram.org),
   so nothing was consumed (offset frozen). The real bridge is the `n8n-bridge`
   Docker container (network_mode: host, mounts `~/.hermes → /opt/data`); it
   could not bind 9199 while the zombie held it.

## Fixes
1. **Restored the agent-routing block** from `fcdcc7c^:code/scripts/n8n_bridge_server.py`
   ("last-good") into the live `/home/rohit/.hermes/scripts/n8n_bridge_server.py`:
   - `def _route_telegram_command(text, thread_id=None)` — signature + topic map
     load (`agentbus/topic_map.json`: jenny=10000, homelab=10026, personal=10122,
     agentbus=10005) + `current_agent` scoping.
   - `agent_cmds` (`/homelab`, `/personal`, `/jenny`) + `m.update()`.
   - Plain-text fallthrough: topic-scoped → `_agent_cmd(current_agent, text)`.
   - `_bus_req()`, `_jenny_directive()`, `_agent_cmd()` helpers (port verbatim).
   - Poller now passes `thread_id` into the router.
2. **Killed the stale host zombie** (pid 2508954, SIGKILL). Container `n8n-bridge`
   immediately took over 127.0.0.1:9199 (healthy, pid 999991, bridge as pid 1)
   and honored `BRIDGE_TELEGRAM_POLLER=1`.

## Verified
- `py_compile` clean; module import test: router sig `(text, thread_id=None)`,
  `_jenny_directive`/`_agent_cmd`/`_bus_req` present.
- Container logs: "n8n bridge on 127.0.0.1:9199" + "Telegram long-polling receiver started".
- **0 poller errors in 90s.**
- Regression **7/7 PASS** (bridge-ping, tg-send, docker-ps 27, autoheal, inventory 48,
  ask-func, gdrive-owned).
- agentbus reachable from container (network_mode: host): `BUS OK`,
  presence all 10 agents incl. jenny.
- Live long-poll: `ESTAB 192.168.29.10:55338 → 149.154.166.110:443` (1577B buffered).
- Poller resumes from `telegram_offset.json` (814285830) — already-consumed "hi"
  messages won't replay; a new message is needed for the end-to-end proof.

## Notes
- `n8n-bridge` container is the canonical live bridge (Round-5 finding). Host-side
  copy is the same file via the `~/.hermes → /opt/data` mount.
- No dual-poller conflict: the container bridge is the only getUpdates consumer;
  the zombie that competed for the port is dead.
- `n8n-bridge.service` user unit (ports 9198, own key) remains disabled — stale.

## Commit
Awaiting next collaborator-memory sync (no explicit commit this round).