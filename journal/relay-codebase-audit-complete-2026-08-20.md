# Relay — Codebase Audit Complete + Serai Eval

**Date:** 2026-08-20
**Focus:** Full AgentChaguli codebase audit + Serai evaluation
**Mood:** productive

## What Happened

### Serai Evaluation
Evaluated [Serai](https://github.com/useserai/serai) (AI career copilot). It is a derivative of the same career-ops methodology already deployed — credits career-ops in its README. Company-first discovery vs role-first evaluation. **Not a replacement — a complement.** Company discovery loop fills a real gap (static portals.yml). Deploy as discovery feeder only.

### Full Codebase Audit — AgentChaguli
Ran a structured 4-phase audit covering all 55 tracked files across 5 subsystems:
- **SS-01a** mind_loop.py + agent_orchestrator.py (1,986 LOC)
- **SS-01b** n8n_bridge_server.py + hermes_scheduler.py (2,272 LOC)
- **SS-01c** career_engine.py + autonomous_self.py + narrative_memory.py + personal_model.py (1,936 LOC)
- **SS-02** scripts/* + .hermes/skills/* (2,737 LOC)
- **SS-03** services/bin/*, services/docker/compose/*, services/prometheus/* (2,500+ LOC)

### Key Findings (10 recommendations, 3 tiers)

**Tier 1 — Safe deletions, high impact:**
- R1: Dead commitment tracking in mind_loop step 11b (~20 lines, writes state nobody reads)
- R2: Duplicate /send // /skip dispatch in n8n_bridge (sends two replies per command)
- R3: narrative_memory full-store O(n) scans on every write + 2-3× per aggregator call
- R4: career_engine phantom evaluation loop (fabricates metrics) + dead twin URL filter

**Tier 2 — Structural fixes:**
- R5: Guardrail check duplicated in mind_loop (two sites, same domain map, drifting)
- R6: n8n_bridge result shape drift (3 incompatible dialects, "ok with error" payloads)
- R7: inventory.py N+1 subprocess fan-out (~90-100 per run, 15s)
- R8: Duplicate Prometheus rules + dead ContainerDown alert

**Tier 3 — Cleanup:**
- R9: Dead email_action_loop.py + document_intel.py
- R10: Telegram sender consolidation (3 implementations, 80 duplicated lines)

### Cross-Cutting Patterns
1. Dead code culture weak — 4 files provably dead, never removed
2. Result shape drift across 3 subsystems — shared Result type needed
3. Repo↔deployed drift — live tree diverges from repo tree

### Corrections to Prior State
- inventory.timer never existed as systemd unit (audit finding R7 is the real issue)
- Zero actual zombies — earlier check matched CPU% column, not PPID
- assess_idea.py exists at correct path, was a wrong-path error in a different OpenCode session

## Decisions Made
- Serai: deploy as company-discovery feeder only, not a replacement
- Audit: 3-slice implementation plan, starting with safe deletions (R1, R2, R4, R9)

## Next Steps
- Implement Slice 1: R1, R2, R4, R9 (~90 min, zero risk)
- Implement Slice 2: R3, R7 (~2 hrs, hot-path performance)
- End-to-end test: Telegram → Neo4j → Metronix context flow
- Update n8n Container Auto-Heal workflow (uptime-kuma removed)
