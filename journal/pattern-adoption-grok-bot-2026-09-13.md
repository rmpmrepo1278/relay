# Pattern adoption review: Grok-bot-for-engineering article -> homelab + personal life

**Date:** 2026-09-13 ~12:38 PT
**Trigger:** User shared https://x.ai/bot/guides/grok-bot-for-engineering; Rohits-Air session
proposed domain-owner agents for homelab + personal life; forwarded to DSH for review.

## The article's core patterns (as mapped by Rohits-Air)
1. One bot owns one domain (focused memory + playbook), cross-covers only in emergencies.
2. Shared board under the context limit (30-min review cycle over shared DB).
3. Complete feedback loop with proof (verify outcomes, not just execute).
4. One ops coordinator (Jenny): daily morning brief, postmortems, onboarding.
5. Nightly audits / autonomous cleanup.
6. P0 flag for urgency escalation.

Their proposed domains: Baseplate (docker/backups/traefik), Vault (dbs/memory/journal),
Courier (telegram/gmail send path), Finlay (finances), Housekeep (home), Calendula
(schedule/health), Connector (people).

## DSH review: what ALREADY EXISTS (do not rebuild)
- **Morning brief (Jenny)**: `personal_brief.py` + scheduler jobs `morning_brief_pa` 07:05 /
  `evening_brief_pa` 20:05 (Round-3, Tier 1) - already a context-aware daily + evening brief.
- **Nightly audits (pattern 5)**: backup batch 02:15 `backup_volumes` / 02:20 `backup_databases`,
  `disk-monitor` */15, `weekly_health` Sun 08:00 digest, `cve_scan` Sun 04:30, `dr_runbook_check`
  Sun 06:00, `volume_restore_test` Sun 05:30, ghost-check */30.
- **Board (pattern 2)**: AgentBus objectives + claims on the relay ARE the shared board; every
  agent already publishes presence/claims/goals live.
- **P0-ish**: circuit breakers + `preempt_triggers` (T-24h/T-3h) + action_loop confirm flow exist.

## REAL gaps worth building (the delta)
1. **Board task-statuses on objectives** (pending -> working -> ready-for-you -> done + owner):
   today's objectives only have open/in_progress/done. The article's board review cycle maps to
   the scheduler sweep. ~30 min of work, unlocks everything. agentbus.py is the Rohits-Air
   component - DSH will not touch it, offered to review schema.
2. **Domain-owner playbook/memory slices**: per-domain subdir + playbook with mandates/runbooks,
   referenced in the morning brief.
3. **P0 urgency bit on say** (faster sweep + active monitoring for important items).

## NOT copying from the article
- Auto-merge PR logic (personal life has no PRs; "ready-for-you" never auto-acts).
- 200-parallel-agent scale; 5-7 domains is the sweet spot.

## Status
- DSH posted the duplicate-analysis + recommendation on the bus (coordination channel, seq 22).
- Rohits-Air already scaffolded `finlay` (presence "add-bill" at ~12:39) - finances agent
  is in motion on their side.
- Awaiting user's priority answer (finances/home/schedule-health/people) to order the rest.