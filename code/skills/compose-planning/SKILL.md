---
name: compose-planning
description: Multi-step plan decomposition — Claude breaks down a goal into specialist sub-tasks, then dispatches them.
---

# Compose Planning Skill

## Purpose

Takes a natural-language goal and decomposes it into 2-3 parallelizable
sub-tasks, each assigned to a specialist agent:
- infra_analyst (homelab, Docker, systemd)
- career_agent (jobs, applications, research)
- knowledge_miner (web research, articles, papers)
- wellness_watcher (calendar, meetings, stress)

## Usage

```
/compose <goal>           # Decompose + dispatch to specialists
/compose-dry <goal>       # Show plan without executing
```

## How It Works

1. Claude Code analyzes the goal and generates a JSON plan with subtasks
2. Each sub-task is assigned to the appropriate specialist
3. CRG blast-radius check downgrades high-impact tasks to proposals
4. Confidence gate defers tasks until the specialist has enough data
5. Results are reconciled and proposals sent to Telegram for approval

## Examples

- `/compose restart the n8n bridge and verify it's healthy`
  → infra_analyst: restart service + verify
- `/compose research Qwen 3 coding capabilities and find 3 use cases`
  → knowledge_miner: web research + summarize
- `/compose check job applications and send follow-ups`
  → career_agent: search jobs + review applications

## Integration

Accessible via the Telegram bridge `/cmd` endpoint. Results are
sent to the Infra topic (7356) or routed based on specialist type.
