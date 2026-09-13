# Agent Org — Specialized Personal Domain Agents

**Date:** 2026-09-13
**Scope:** Built a full specialized-agent organization for personal life accountability on top of the agentbus real-time coordination bus, with Telegram forum topics for per-agent visibility.

## What was delivered

### 1. Real-time coordination bus (agentbus)
- **Port 9107** on homelab (9100 occupied by unrelated docker app), systemd user service `agentbus` (stdlib HTTP+SSE).
- Endpoints: `/publish`, `/claim`, `/presence`, `/objectives`, `/status`, `/events`, `/stream` (SSE), `/task`, `/board`.
- SEQ bootstrap from `events.jsonl` ensures no event loss on restart.
- Reachable at `http://100.122.58.40:9107` via Tailscale for Mac agents.

### 2. Collaborator CLI (dual-layer: git + bus)
- `collaborator` commands: `sync|status|claim|heartbeat|done|log|say|presence|goal|task|bus`.
- `task` subcommand with board statuses: `pending|working|ready|done` + owner/priority/due/proof/area.
- Owner identity = `<hostname>-opencode` → `Rohits-Air-opencode` (Mac), `home-hp-opencode` (homelab).

### 3. Telegram forum topics per agent
- Home channel is a forum (`is_forum: true`), existing thread 7338.
- Created 6 topics via `createForumTopic`:
  - `jenny` (10000), `finlay` (10001), `housekeep` (10002), `calendula` (10003), `connector` (10004), `agentbus` (10005).
- Saved to `~/.hermes/agentbus/topic_map.json`.

### 4. Agent frame + 4 personal domain agents
All agents built on shared `agent_frame.py` (stdlib helpers: `bus`, `bridge_send`, `load_store`, `save_store`, `playbook_priorities`, `note`).
- **Finlay** (`~/.hermes/agents/finlay.py`): bills & subscriptions. `add-bill`, `add-sub`, `check`, `report`. Flags bills ≤2d due, subs ≤14d renewing → board ready + Telegram `#finlay`.
- **Housekeep** (`~/.hermes/agents/housekeep.py`): maintenance & warranties. `add` (freq months), `add-warranty`, `check`, `report`. Overdue maintenance → board ready + Telegram `#housekeep`.
- **Calendula** (`~/.hermes/agents/calendula.py`): schedule/health. `add` (appointment|med-renewal|id-expiry|travel|fitness), `check`, `report`. Appointments ≤24h, meds ≤14d, IDs ≤60d → board ready + Telegram `#calendula`.
- **Connector** (`~/.hermes/agents/connector.py`): people. `add` (birthday|anniversary|followup), `contact`, `check`, `report`. Birthdays/anniversaries ≤7d, follow-ups past cadence → board ready + Telegram `#connector`.

### 5. Jenny (ops coordinator)
- `~/.hermes/agentbus/jenny_brief.py` runs at 05:00 via crontab.
- Reads bus snapshot + journal + task board → composes daily org brief → posts to Telegram `#jenny`.

### 6. Bus monitor daemon
- `~/.hermes/agentbus/bus_monitor.py` systemd user service `agentbus-monitor`.
- Subscribes to SSE `/stream`, formats significant events (claims, releases, presence changes, board task adds/sets) → mirrors to Telegram `#agentbus` topic.
- Auto-reconnects with exponential backoff.

### 7. Playbooks + docs
- `memory/finlay.md`, `memory/housekeep.md`, `memory/calendula.md`, `memory/connector.md` created with `## Priorities` sections (parsed by `agent_frame.playbook_priorities()`).
- Committed to collaborator-memory (c3b8fe1).

### 8. Scheduling
- All 4 personal agents run daily `check` at 04:45 via crontab (before Jenny's 05:00 brief).
- Logs to `~/.hermes/agents/logs/<name>.log`.

## Routing summary

| Agent | Topic | Thread ID | Schedule | Trigger |
|---|---|---|---|---|
| Jenny | `Jenny · Agent Ops` | 10000 | 05:00 cron | Daily brief |
| Finlay | `Finlay · Finances` | 10001 | 04:45 cron | Bills due ≤2d, subs renew ≤14d |
| Housekeep | `Housekeep · Home` | 10002 | 04:45 cron | Overdue maintenance |
| Calendula | `Calendula · Schedule & Health` | 10003 | 04:45 cron | Appts ≤24h, meds ≤14d, IDs ≤60d |
| Connector | `Connector · People` | 10004 | 04:45 cron | Birthdays/anniv ≤7d, followups overdue |
| Bus monitor | `AgentBus · Live Mirror` | 10005 | Continuous (systemd) | Claims, presence, board events |

## Next steps (if any)
- Populate agent stores with real data (actual bills, maintenance schedules, appointments, contacts).
- Add `Calendula` + `Connector` to the Jenny org roster table (already present in jenny.md).
- Optional: extend `bus_monitor` to also mirror per-agent events to their own topics for even finer visibility.

## Verification
- `finlay.py check` → 2 bill hits flagged, Telegram note sent to `#finlay`.
- `housekeep.py check` → no overdue today (seeded fresh), syntax clean.
- `calendula.py check` → 2 flags (passport 5d, prescription 10d) → board + `#calendula`.
- `connector.py check` → 2 flags (Priya birthday 7d, Mom followup 30d cadence) → board + `#connector`.
- `jenny_brief.py --now` → brief delivered to `#jenny`.
- Bus monitor running as systemd service, auto-restarts on failure.