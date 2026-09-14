# Autonomous Agent Conversion — 2026-09-13

## What Was Done

Converted all 6 personal agents from deterministic Python scripts to autonomous Hermes-framework agents using the 7-phase mind loop (OBSERVE → CONNECT → ANTICIPATE → PLAN → ACT → REFLECT → EVOLVE).

### Files Created (deployed to ~/.hermes/scripts/ on homelab)
- `autonomous_agent.py` — base class (cycle loop, Telegram, memory, presence heartbeat, dedup)
- `jenny_agent_autonomous.py` — Chief of Staff (board coordination, onboarding, daily brief)
- `homelab_agent_autonomous.py` — Infrastructure (Docker, systemd, disk, memory, backups, updates)
- `finlay_agent_autonomous.py` — Finance (bills, subscriptions, budget anomalies)
- `housekeep_agent_autonomous.py` — Home maintenance (maintenance tasks, warranties)
- `calendula_agent_autonomous.py` — Schedule/Health (appointments, meds, ID expiry)
- `connector_agent_autonomous.py` — People/Relationships (birthdays, anniversaries, follow-ups)

### Systemd Services (enabled + active)
- jenny-agent.service (30min cycle)
- homelab-agent.service (15min cycle)
- finlay-agent.service (60min cycle)
- housekeep-agent.service (60min cycle)
- calendula-agent.service (60min cycle)
- connector-agent.service (60min cycle)

### Bugs Fixed
1. **Telegram 400** — `_send_telegram_api` 400 error from Markdown unescaped `_` in status strings like `updates_available`. Fixed: base class now calls `_md_escape()` on all messages before sending.
2. **False systemd "degraded"** — `systemctl --user is-active <services>` output parsing checked service name in status text (always failed). Fixed: use `list-units --state=failed` and filter results.
3. **Calendula/Connector generator crash** — `connect()` used `yield` making it a generator; base class couldn't concatenate. Fixed: changed to `insights.append()`.
4. **Connector/Calendula act() yield** — Same `yield` bug in `act()`. Fixed to `results.append()`.

### Improvements
- **Presence heartbeat** — all agents now POST `/presence` each cycle, appearing in agentbus status.
- **Jenny dedup** — added `_is_handled()`/`_mark_handled()` with TTL to avoid re-coordinating old tasks every cycle. Capped at 8 actions per cycle.
- **Jenny path fix** — replaced Mac `/Users/rohitmishra/...` paths with `Path.home() / ".hermes" / ...` for homelab compatibility.

## Current State
- All 6 agents: systemd active, zero errors
- All 6 agents reporting presence on agentbus
- Zero Telegram send errors
- Jenny: 15 cycles, 0 errors
- Homelab: 7 cycles, 0 errors
- Board: 49 ready tasks (old debt from deterministic cron agents)

## Known Issues / Next Steps
1. Old 04:45 crontab (finlay, housekeep, calendula, connector) still runs deterministic checks + creates board tasks. Retire crons once autonomous agents prove stable.
2. Jenny's 66→54 insights per cycle due to 49 stale board tasks — dedup will drain them over ~3 hours. After that, cycles should produce 0-3 insights.
3. finlay/housekeep presence shows "check" from deterministic agents — autonomous heartbeat overwrites on next cycle. Name collision with Hermes mind_loop autonomous agents (also named finlay, calendula, etc.) is benign for now.
4. Topic routing loose ends: agent_frame.py `topic_id()` still returns 7338 for finlay/housekeep/calendula/connector (old topics removed from map). Cron notes go to General thread, not personal 10122.
5. `homelab_agent.py` (deterministic) `_get_topic_id()` returns agentbus 10005, not homelab 10026.

## Validation Checklist (User-Pasted, Pending)
- [ ] Test all agent flows end-to-end (dedup, Telegram, board, Jenny)
- [ ] Build LLM Inference Research Agent
- [ ] Wire agents across board (cross-agent dependencies, shared context)
- [ ] Validate Jenny daily 1:1 with each agent + offline operation
- [ ] Full regression (7/7 agents, Jenny, Telegram, board)
