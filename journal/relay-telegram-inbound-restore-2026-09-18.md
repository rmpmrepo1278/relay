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
- Regression **7/7 PASS** (post-fix end-state; tg-send is throttle-accept PASS —
  real egress proven by the live replies below, not the regression).
- agentbus reachable from container (network_mode: host): `BUS OK`,
  presence all 10 agents incl. jenny.

## Follow-up correction — the REAL root cause (same day)
The fix above restored the routing code, but inbound was STILL dead and offset
still frozen at 814285830. Probe `getUpdates?offset=0` showed the user's messages
(814285831–838, incl. "hi"×3, "Hello??!!", "When is the travel certificate
expiring?", topic 10000) **retained and unconfirmed** — Telegram was never
delivering them because the running bridge never actually polled with a token:

- **The `n8n-bridge` container runs with `HOME=/opt/data`** (docker-compose
  sets it explicitly; `working_dir: /opt/data`, mount `~/.hermes:/opt/data`).
- The bridge script resolves everything as `Path.home()/.hermes/...` →
  `/opt/data/.hermes/...`, which does NOT exist (would need the host's
  `~/.hermes/.hermes`). `_ENV_PATH` is therefore missing → `TELEGRAM_TOKEN=None`.
- `_telegram_get_updates()` swallows exceptions (`except Exception: return None`)
  → every poll was a `botNone/getUpdates` 404 → silent `None` → `sleep(1)` loop.
  **Zero error logs.** The earlier "0 errors in 90s" + "ESTAB → 149.154.166.110"
  observations were this failed request / buffered 404 response, not a healthy poll.
- The `tg-send: PASS` regression line is throttle-**acceptance**, not delivery —
  it never exercised real egress, which is why the outage was invisible for days.
- All `Path.home()/.hermes` paths in the script (env, offset, throttle, topics,
  scripts, state) were equally broken in-container: the container bridge has
  likely NEVER sent a real Telegram message.

## Real fix
`docker-compose.yml` `n8n-bridge` service:
- `HOME: /opt/data` → `HOME: /home/rohit`
- added mount `- /home/rohit/.hermes:/home/rohit/.hermes`
Backup: `docker-compose.yml.bak-20260918-115709`. Recreated with
`docker compose up -d --no-deps n8n-bridge` (container 722d69f47012).

## Proof (end-to-end, live)
- Offset file advanced `814285830 → 814285838` on first poll after recreate; all 8
  queued messages consumed and routed:
  - `Hi` (831) → `jenny-1789757959-c1a529` **done, replied**
  - `When is the travel certificate expiring?` (832) → `jenny-1789757960-d64e33`
    **done, replied**
  - `Hello??!!` (833) / `hi` (834, 838) → jenny tasks; 833 **done, replied**,
    834 **done, delegated_to:finlay**, 838 ready → picked up next cycle
  - `Hi` (835, topic 10026 homelab) → homelab agent; `Hola` (836, no topic) →
    magnitude reply; `/new@ChaguliBot` (837) → "Unknown command"
- Poller and sender share `TELEGRAM_TOKEN`; poller pulling updates proves the
  token loads — jenny's `proof=replied` marks reflect real /sendMessage egress.

## Notes
- Gateway/dashboard containers have the same `HOME=/opt/data` pattern: their
  Telegram platform (if ever enabled) would silently 404 the same way. Out of
  scope here; noted for a future round.
- Remediation is compose-schema (rebuild-safe); no host-file pollution.

## Notes
- `n8n-bridge` container is the canonical live bridge (Round-5 finding). Host-side
  copy is the same file via the `~/.hermes → /opt/data` mount.
- No dual-poller conflict: the container bridge is the only getUpdates consumer;
  the zombie that competed for the port is dead.
- `n8n-bridge.service` user unit (ports 9198, own key) remains disabled — stale.

## Commit
Awaiting next collaborator-memory sync (no explicit commit this round).