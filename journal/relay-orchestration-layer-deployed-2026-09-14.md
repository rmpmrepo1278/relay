# Relay — Orchestration Layer Deployed

## What was built (Sep 14, 2026)
Stitched the 10-agent team into a working Chief-of-Staff orchestration layer:

### 1. agent_orchestrator.py — bus-task dispatch for loop agents
- `LOOP_AGENTS` set: baseplate, vault, courier, inference, finlay, housekeep, calendula, connector
- `create_bus_task()`, `list_bus_tasks()`, `claim_bus_task()`, `complete_bus_task()`, `delegate_task_to_agent()`
- `classify_task()` + `_loop_agent_for_content()` keyword table maps free-text → loop agent
- `dispatch()` routes loop agents to async bus tasks; sync specialists (homelab, infra, career, knowledge, wellness) unchanged
- `decompose_plan` respects `goal_domain` matching loop agents

### 2. agent_loop.py — consumes bus tasks each cycle
- `consume_assigned_tasks(max_tasks=2)` added before decide/execute
- Reads `/board`, filters `area == NAME` + status pending/ready, claims, runs `execute_domain(shlex.split(title))`, completes with proof, appends reflection
- Tested: baseplate consumed "check disk usage and report" → proof "check done — 0 alerts"

### 3. Bridge (/jenny, /team, /delegate)
- `/jenny <instruction>` → `_jenny_directive()` → bus task area=jenny, owner=rohit, status=ready; confirms to user
- `/team` → `_team_status()` → reads `/status` presence (epoch `ts` float) + board; shows roster with age + open task counts per agent
- `/delegate <agent> <task>` → `_delegate_to_agent()` → bus task to agent area; backward-compatible: single arg falls through to `/claude` legacy path
- `/jenny` with no args → brief (unchanged)
- Existing `/claude` preserved

### 4. Jenny — directive handling + delegation
- `observe()`: enriched board tasks with `key` (bus task key from dict key) so act() can mark source tasks done
- `connect()`: `user_directive` insight when `area=="jenny"` and `owner in ("rohit","user","me")`
- `plan()`: `user_directive` branch → `_route_directive(title)` keyword table → target agent
- `act()` delegate branch: sends confirmation to own topic (10000); marks source directive task done on bus
- `_route_directive()`: keyword table routing finlay→finance, baseplate→infra, connector→people, etc.; default homelab

## Verified end-to-end
1. `/jenny check disk usage and follow up on the failed bills` → bus task area=jenny
2. Jenny cycle → observe picks up directive → connect → user_directive insight → plan → delegate to baseplate (keyword "disk")
3. Jenny act() → `delegate_to_agent("baseplate", content)` → `dispatch_plan` → bus task area=baseplate
4. Jenny confirms to own topic (10000): "📤 Delegated to *baseplate*..."
5. Baseplate loop → consume_assigned_tasks → claims task → execute_domain(["check","disk","usage","and","follow","up","on","the","failed","bills"]) → completes with proof
6. Directive task marked done on bus

## Known gaps (acceptable)
- `_route_directive` keyword table is best-effort; unknown text defaults to homelab
- Open tasks from earlier (14 finlay, 13 calendula, 12 connector) are existing backlog — not new failures
- `baseplate-1789406038-92ad7d` and smoke test tasks from earlier: done
- Stale `bil-electricity` "failed" with proof "Unknown command: [bill]" — existing finlay domain script issue, not our orchestration

## Commit
`2026-09-14` — orchestrator + agent_loop + bridge + jenny — deployed + verified
Backups at `~/.hermes/backups/orchestration-20260914-101311/`
