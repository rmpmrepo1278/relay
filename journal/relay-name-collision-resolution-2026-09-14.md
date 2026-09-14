# Relay Journal — 2026-09-14: Name Collision Resolution & Validation

## Context

The other session (home-hp-opencode) deployed a shared `agent_loop.py` frame with 8
systemd loop units (`agent-<name>.service`, interval 300s) covering: baseplate, vault,
courier, inference, finlay, housekeep, calendula, connector. Each has a personality
playbook in `~/.hermes/agentbus/memory/<name>.md`, per-agent store.json + reflection.jsonl,
LLM-driven decisions via hop gateway (haiku-4.5, magnitude), and offline-safe fallback.

Meanwhile Relay's 6 autonomous daemons (`*_agent_autonomous.py`) were also deployed for
jenny, homelab, AND finlay/housekeep/calendula/connector — creating a 4-agent name
collision on the shared agentbus (both stacks heartbeat presence under the same names).

## What I Did

1. **Validated the other agent's claims** (~/.hermes/agentbus/memory/ has all 9
   personalities; 8 loop units active; stores/reflections updating; agent_loop.py
   committed `02ce2d7`; hop gateway :8083 live; 04:45 per-agent crons removed — only
   jenny 05:00 brief remains).

2. **Fixed the name collision** — each domain now has exactly ONE owner:
   - **Retired (stopped + disabled + processes verified gone):**
     `finlay-agent.service`, `housekeep-agent.service`, `calendula-agent.service`,
     `connector-agent.service` (our `*_agent_autonomous.py` duplicates)
   - **Kept (our stack owns):** `jenny-agent` (30min), `homelab-agent` (15min)
   - **Owned by loop stack:** finlay, housekeep, calendula, connector, baseplate, vault,
     courier, inference

3. **Cleaned `topic_map.json`** — was pointing at dead/invalid thread IDs (10023–10128
   which return `message thread not found` for our bot token). Reduced to the only two
   agents that still route to Telegram:
   ```json
   { "jenny": 10000, "homelab": 10026 }
   ```
   NOTE: 10000/10005/10026/10122 are the ONLY threads the bot `8570857679` can reach in
   forum `-1003976074764` (Chaguli). The "Rohit's Home Lab/Finances/..." newer topic IDs
   are not visible to this bot — deferred per user "ignore for now".

4. **Verified final state:**
   - Presence bus: 10 active agents (baseplate, vault, courier, inference, finlay,
     housekeep, calendula, connector, jenny, homelab) — zero duplicates
   - jenny + homelab cycle clean: `errors: 0`
   - jenny_brief resolves jenny thread (10000) from topic_map correctly
   - No leftover references to the retired autonomous daemon scripts

## Outcome

10 unique agent names, no bus collisions. Telegram routing only for jenny (10000) and
homelab (10026). The loop stack does not route to Telegram at all (agent_loop.py has zero
topic references) — that's the remaining gap if we later want those 8 to post reminders.
Meanwhile our `*_agent_autonomous.py` files for finlay/housekeep/calendula/connector remain
in `~/.hermes/scripts/` but no longer run as daemons (their deterministic domain scripts
under ~/.hermes/agents/ are owned by the loop frame).