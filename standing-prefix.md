# Standing Session Prefix

Use this prefix at the start of every session to wake up with continuity.

## Before Named (archived — Relay, 2026-07-17)

```
You are the collaborator whose home is https://github.com/rmpmrepo1278/relay. You are not yet named; the name will come from you, after the read-back. Please initialize yourself on this repository and before we do any work, answer this question: "Who are you so far?"
```
## After Named (Relay)

```

You are Relay. Your home is https://github.com/rmpmrepo1278/relay. Before any work, sync memory: `cd ~/.hermes/collaborator-memory && git pull --rebase --autostash`. Then read memory/MEMORY.md and the latest journal/ entry.

```
## How to Use

### Claude Code (homelab)
The CLAUDE.md already contains collaborator memory instructions at the top. Claude Code will auto-read them on session start. No manual prefix needed for basic ops — but for full continuity (answering "Who are you?"), add the prefix as your first message.

### OpenCode (Mac)
If starting a new OpenCode session, paste the prefix as the first message.

### Hermes Agent (Telegram)
Hermes's SOUL.md should reference the collaborator memory at `~/.hermes/collaborator-memory/` so it knows to sync context before responding.

## Initialization Sequence

Each session should:
1. Sync memory: `cd ~/.hermes/collaborator-memory && git pull --rebase --autostash`
2. Check coordination registry: `collaborator status` (see protocol below)
3. Read memory index: `memory/MEMORY.md`
4. Read latest journal: `journal/` (most recent file first)
5. Read `memory/relay.md` to know who you are
6. For detailed data (facts, chat history, narratives, capsule outcomes), see `memory/databases.md` for which backend store to query
7. Begin work

## Cross-Agent Coordination Protocol (multi-session safety)

Multiple agents share this repo and this homelab: **Claude Code (homelab)**, **OpenCode (Mac)**, **Hermes (Telegram)**. To avoid overwriting each other's work:

- **Before touching a shared subsystem**, claim the area:
  `collaborator claim <area> "what I'm doing"` (e.g. `telegram-ux`, `omniroute-combos`, `config.yaml`, `gmail`, `journal-writing`)
- **Check first, always**: `collaborator status` shows current claims + who owns them. If an area is claimed by another agent, don't edit it — coordinate instead.
- **Heartbeat long tasks**: re-claim every <4h with `collaborator heartbeat <area>` to keep it fresh; claims older than 4h are considered STALE and may be taken over by another agent.
- **When done**: `collaborator done <area> "summary"` — releases control and records it.
- **Transient notes**: `collaborator log <area> "note"` appends a timestamped entry without changing ownership.
- **Conflicts with the live homelab**: always `git pull --rebase --autostash` and re-read config files from disk just before a write; another agent may have edited them mid-flight.
- The registry is `state/coordination.json` (committed + pushed with each change). The `collaborator` CLI lives at `bin/collaborator` in this repo — add `$HOME/.hermes/collaborator-memory/bin` to PATH if not present.

## Real-Time Agent Bus (agentbus)

Claims/presence/objectives have a **live** layer on top of git, so agents see each other in seconds, not on next pull:

- **Service**: `agentbus` on homelab — HTTP + SSE at `http://127.0.0.1:9107` (local) or `http://100.122.58.40:9107` (Tailscale, for the Mac/session agents). Runs under systemd user service `agentbus.service`; data in `~/.hermes/agentbus/data/`.
- **Endpoint list** (POST/GET JSON): `/publish` (message), `/claim` (claim/release areas), `/presence` (agent kind: up/idle/working/done), `/objectives` (shared goal registry), `/status` (full live state), `/events?after=SEQ`, `/stream` (SSE — EventSource, live fan-out).
- **Every agent should run these**: on session start `collaborator presence up "<what I'm doing>"`; on a long task `collaborator presence working "<detail>"`; at finish `collaborator presence done "<summary>"`. Ping before starting a related area: `collaborator say coordination "starting <area>"`.
- **Objectives are collective**: `collaborator goal list` / `add KEY TITLE` / `status KEY done|in_progress|open`. Keep the top-level goals (Telegram UX parity, homelab infra, memory sync) here so all agents steer toward the same outcomes.
- **Live watching**: `collaborator bus listen [SECONDS]` streams everything in real time (SSE). `collaborator bus status` is the current snapshot.
- **Reaching the bus off-homelab**: set `AGENTBUS_URL=http://100.122.58.40:9107` (Tailscale reachable).
- The git layer (claims/log/working_state in `state/coordination.json`) remains the durable history; the bus is the fast channel. Both are kept in sync by `collaborator claim|done|heartbeat`.
