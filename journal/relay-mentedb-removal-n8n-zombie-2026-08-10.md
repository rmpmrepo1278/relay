# Relay: MenteDB removal completed + zombie n8n workflow killed (2026-08-10)

## Context
User asked: "are we using mentedb? is it redundant now that hermes/CC/opencode memory is consolidated?" Verdict: **yes, redundant.** MenteDB (community Rust "cognitive memory graph", image `ghcr.io/nambok/mentedb`) has NO code consumers — grep of hermes-agent/scripts found only prose mentions (SOUL.md, reflexion jsonl). Its only dependents were monitoring: n8n "MenteDB Health Check" workflow, `service-registry.yml`, and the health dashboard. The consolidated brain is `unified_memory.db` (85.6 MB). `memory/databases.md` already recorded mentedb as removed per user request — but the removal was INCOMPLETE, leaving the zombie alert loop behind.

## Alert source (false positive)
n8n workflow "MenteDB Health Check" (id `VBjlmcMFzOwmmyIR`, hourly schedule) pings `http://172.18.0.1:6677/health` — **wrong path**. MenteDB's real health endpoint is `/v1/health` (returns `{"status":"ok"}`); `/health` returns 404 → Evaluate node sees no `status` → sends "🧠 MenteDB is DOWN / Service needs restart". So the alert fired even while the service was healthy.

## n8n DB surgery (gotcha documented)
To kill the workflow: stopped n8n, edited `compose_n8n_data` volume DB via `python:3-alpine`. **First attempt failed silently**: my script matched `workflowId` columns only, but `workflow_entity` keys on `id` — so the DELETE skipped it; only executions/related rows (which use `workflowId`) were removed, while `workflow_entity` kept the workflow (createdAt 2026-07-25). Verified-misleading symptoms: row persisted, execs=0, DB mtime bumped at n8n startup → wrongly inferred a "restore from backup". **Corrected**: delete `workflow_entity WHERE id=?` too → 0 rows while stopped, 0 after restart. Workflow permanently gone.
- n8n volume DB backups exist at `/home/rohit/services/data/n8n/` but are OLD (Apr/May) — NOT the source of the "restore" phantom.

## Full mentedb removal (undoing my earlier recreate + leftover refs)
- Removed `mentedb` service block from `services/docker/compose/apps.yml` (validated: `docker compose config -q` OK).
- Removed entry from `services/service-registry.yml`.
- `docker rm -f mentedb`, `docker rmi mentedb:fixed`, `sudo rm -rf /home/rohit/services/mentedb` (data dir was root-owned by the container).
- Port 6677 closed. Container/image/dir all gone.

## Related: auto-fix churn during triage
Stopping n8n triggered the autonomous fixer ("Container n8n has exited", hermes_mind.py) which created snapshot commit `78a93b9e8 auto-fix-snapshot` on hermes-agent repo (harmless — sits ON TOP of the delegate-tracking commit `d49953fb4`; delegate intact). The fixer's `git checkout <sha>` "rollback" strategy is fragile and caused the earlier repo churn; worth reviewing separately.

## Files changed
- homelab: `services/docker/compose/apps.yml`, `services/service-registry.yml`, n8n `compose_n8n_data` volume DB, deleted mentedb container/image/dir.
- memory: `memory/databases.md` (mentedb removal detail), `memory/homelab-infrastructure.md` (mentedb struck-through removed).
