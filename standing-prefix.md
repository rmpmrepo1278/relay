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
