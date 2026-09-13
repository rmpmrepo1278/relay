# Homelab Agent Onboarded — Autonomous Infrastructure Specialist

**Date:** 2026-09-13
**Agent:** `homelab` (infrastructure admin)
**Onboarded by:** Jenny (Chief of Staff) per mandate #4
**Process:** `memory/agent_onboarding_template.md` 9-step checklist

## What Was Delivered

### Agent Script
- `~/.hermes/scripts/homelab_agent.py` — 620 lines, stdlib-only
- Health checks: Docker (27 containers), systemd (6 critical), disk, memory, Kopia backups, apt updates, agentbus
- Self-heal: container restart, systemd restart, disk cleanup, agentbus restart — all rate-limited
- Orchestrator interface: `homelab_agent(task)` returning structured results
- CLI: `check`, `heal`, `docker-pull`, `verify-backups`, `updates [security]`, `restart`, `status`

### Integration Points
| Layer | Registration |
|---|---|
| **Orchestrator** | `agent_orchestrator.SPECIALISTS["homelab"]` (priority 10, triggers: docker, container, service, health, backup, disk, memory, uptime, update, apt, kopia, restart, heal, homelab, infrastructure) |
| **Confidence** | `autonomous_self._calibration_bucket("homelab")` → "homelab" (default 0.6) |
| **Telegram** | Topic `agentbus` (thread 10005) — live mirror |
| **Agentbus** | Publishes presence, claims, board tasks |
| **Narrative** | All observations/actions recorded to episodic memory |
| **Cron** | `45 4 * * *` daily check (before Jenny 05:00 brief) |

### Onboarding Artifacts Created
1. **Playbook:** `memory/homelab.md` — mandate, priorities, store, schedule, heal rules, escalation
2. **Template:** `memory/agent_onboarding_template.md` — 9-step checklist, minimal scaffold, Jenny authority
3. **Jenny mandate updated** — explicit onboarding authority, deprecation power, quality gate
4. **Org roster updated** — homelab added to jenny.md table

### Verification
```bash
# Direct
python3 ~/.hermes/scripts/homelab_agent.py check
→ overall: "maintenance_needed" (75 updates, 4 security, backups not_configured)

# Via orchestrator
dispatch_plan({"action":"check","content":"homelab health check","goal_domain":"infra","priority":5})
→ status: "completed", health payload returned, confidence: 0.6

# Telegram delivery
→ Health alerts route to #agentbus topic
```

## Current Health Status (post-onboard)
- **Docker:** 27 containers healthy
- **Systemd:** 6 critical services active
- **Disk:** Healthy (<85% on all mounts)
- **Memory:** 34/62 GiB used, 6.6 GiB swap
- **Backups:** ⚠️ Not configured (Kopia repo disconnected) — flagged for remediation
- **Updates:** 75 available (4 security) — flagged for maintenance window
- **Agentbus:** Healthy (1 claim, 6 presence, 7 objectives)

## Next Actions (Jenny-tracked)
1. **Configure Kopia** — connect repository, verify snapshots < 24h
2. **Schedule security updates** — weekly maintenance window (Sunday 02:00?)
3. **Create dedicated `homelab` Telegram topic** — separate from `agentbus` mirror
4. **Add to hermes_scheduler.py** — replace cron with scheduler Job for better observability
5. **Build `baseplate`/`vault`/`courier`** — remaining homelab trio from org roster

## Framework Proven
The onboarding template works. Adding a new specialist agent now takes:
- ~30 min for a full agent (script + playbook + registration + test)
- ~5 min for a prototype (minimal scaffold + orchestrator registration only)

Jenny's onboarding authority is codified and enforceable via the collaborator CLI.