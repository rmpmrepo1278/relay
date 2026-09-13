# AgentBus: real-time cross-agent coordination layer

Date: 2026-09-13
Author: Relay (opencode, Mac) + DSH session (homelab) coordinated via git layer.

## What and why

The `collaborator` git-based claim registry worked but was **asynchronous** — two
agents (this opencode Mac session + the opencode-web/DSH homelab session) only
saw each other's claims on the next `git pull`. With potentially more agents in
the future, we need a **real-time** channel so all agents collectively steer
toward shared objectives without stepping on each other.

## The bus

- **Service**: `agentbus.py` on homelab — stdlib-only HTTP server (`http.server`)
  with SSE fan-out. Runs as systemd user service `agentbus` (survives reboots).
- **Ports**: local `http://127.0.0.1:9107`, Tailscale `http://100.122.58.40:9107`
  (from Mac/other machines).
- **State**: file-backed JSON in `~/.hermes/agentbus/data/` (events.jsonl,
  claims.json, presence.json, objectives.json). In-memory SEQ bootstraps from the
  event log on restart so SSE subscribers stay aligned.
- **Endpoints**: `/publish` (msg), `/claim` (claim/release areas),
  `/presence` (agent kind: up/idle/working/done), `/objectives` (shared goal
  registry), `/status` (snapshot), `/events?after=SEQ`, `/stream` (SSE live).

## CLI integration (`bin/collaborator`)

- Now dual-layer: git claims (durable history) + live bus (fast channel).
  `claim/done/heartbeat` write to BOTH.
- New subcommands: `say [CHANNEL] MSG`, `presence KIND [NOTE]`, `goal`
  (list/add/status — shared objectives), `bus status|events|ping|listen`.
- `status` shows live bus claims first, then git-layer claims.
- Any agent sets `AGENTBUS_URL=http://100.122.58.40:9107` off-homelab.

## Verified

- Publish → live event → SSE subscriber receives within ~1s (Mac→homelab
  roundtrip confirmed).
- Claims, presence, objectives all roundtrip both directions.
- systemd restart: SEQ recovered (5), SSE still live.
- Fixes along the way: host had a 14-day-old `/app/docker_only_server.py` on
  :9100 (left untouched, chose 9107); a NameError from a mangled heredoc quote
  on `pres[agent]['kind']`; macOS lacks `timeout` so SSE test had to use curl.

## Open items

- Objectives seeded: homelab-opt, memory-sync, telegram-ux-parity. Agents should
  update statuses on the bus (`collaborator goal status KEY done|in_progress`).
- Consider a long-running listener daemon on the Mac so it can react to urgent
  bus messages without being invoked (optional).
- The DSH homelab agent publishes to the same repo (`data/jobs_*.json`); keep
  both layers in sync for durable history.