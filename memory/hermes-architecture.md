---
created: 2026-07-17
confidence: high
source: CLAUDE.md, SOUL.md, hermes_scheduler.py, CHANGELOG.md, autonomous audit
---

# Hermes Architecture

**Alias:** Chaguli
**Role:** Personal Chief of Staff / Autonomous Agent
**Home:** ~/.hermes/ on homelab
**Language:** Python, with shell scripts
**Gateway:** hermes-agent/gateway/ (Telegram integration)
**LLM:** Multi-provider via agentharness-llm-proxy (port 8080)

## Scheduler (hermes_scheduler.py — Daemon)
Replaced 41+ cron entries with unified Python scheduler. 58 jobs defined.
Runs continuously via @reboot crontab.

## Autonomous Mind Layer
- **hermes_mind.py v4** — 3-tier repair (bash/Claude/human), service dependencies, git rollback, predictive patterns, auto-retirement, Telegram control, weekly self-audit (runs every 3 min)
- **mind_loop.py** — OBSERVE→CONNECT→ANTICIPATE→PLAN→ACT→REFLECT→EVOLVE cycle (separate, possibly superseded by hermes_mind.py)

## Homelab Pipeline (Added 2026-07-14)
6 modules, all verified working:
- homelab_discoverer.py (every 6h)
- homelab_evaluator.py (every 6h, offset)
- homelab_deployer.py (daily 5am)
- homelab_troubleshooter.py (every 15min)
- homelab_optimizer.py (Sunday 10am)
- homelab_reporter.py (daily 10:30am)

## Memory Systems
- Knowledge graph (temporal_kg.py)
- Capsule outcome tracking (capsule_tracker.py)
- Reflexion memory buffer (reflexion_memory.jsonl)
- GraphRAG extraction (graphrag.py)
- Memory reflector (skills/chief-of-staff/scripts/memory_reflector.py)
- GNaP prune (gnap.py)

## Career Pipeline
- career_autonomous.py, career_briefing.py
- Weekly skill_gap, auto_followup, company_scan
- career-ops/ project with L linkedin automation

## Gap Map

### Fixed (2026-07-17)
- **Proactive layer**: interest_model.py + proactive_orchestrator.py deployed to scripts/proactive/. Both run every 4h via scheduler. Interest model built from 3 sources (research, telegram, sessions). Orchestrator coordinates curiosity engine and pushes briefings to alerts_inbox.
- **13 failing scheduler jobs**: Root cause found — scheduler uses `cmd.split()` not shell, so `cd &&` commands failed instantly. Fixed: full paths for career-ops scripts, separate shell wrappers for logrotate/disk_watch/unhealthy_restart, timeout increases for slow jobs (cve_monitor 60→300s, package_tracker 60→120s, gdrive_keepalive 30→60s, backup_health 30→60s), career_autonomous.py KeyError bug fixed (state dict missing keys).
- **commitment_executor.py**: Built from scratch. Checks commitments.json every 5min, alerts on overdue/due-soon/stale commitments. Integrates with alerts_inbox → Telegram.
- **task_executor.py**: Built from scratch. Every 15min picks highest-priority pending task from task_queue.json, executes by domain (infra → docker restart/troubleshooter, research → research_consumer, general → auto-detect infra keywords). Clears the stale backlog.
- **self_correction.py**: Built from scratch. Every 10min verifies completed tasks (checks container health, system health). Alerts if fix didn't actually work. Also monitors scheduler failure rate.
- **Feedback loop**: Wired through self_correction.py's state tracking. Records successes/failures per cycle for long-term learning.

### Still Open
- (None critical — all known gaps addressed)
