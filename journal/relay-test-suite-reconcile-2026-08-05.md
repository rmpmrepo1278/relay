# Relay — agentharness stale test suite reconciliation (2026-08-05)

## Context
User asked to build an import-safety guard (done earlier, commit `2e34303`) and fix the stale/failing agentharness regression tests.

## What was done
1. **Real bug fixed**: `core/providers/token_juice.py` referenced undefined `POOL_WORKERS`
   in `_get_process_pool()` (line ~301), which broke `juice_body` caching — every content
   fell through as error → pass-through. Added `POOL_WORKERS = int(os.environ.get("TJ_POOL_WORKERS", os.cpu_count() or 2))`.

2. **35 stale test expectations rewritten** in `tests/test_regression_extended.py`:
   - `EXPECTED_MCP_SERVERS`: was 11 stale server names (docker/files/paperless/browser-use/n8n),
     now the actual 18 gateway servers (backup, code-review-graph, data-management, doctor, git,
     global-chat, global-chat-mcp, graphify-mcp, hermes-memory, homelab-exec, infrastructure-*,
     network, rss, system-docker, system-homelab-ops, system-network). Gateway on :8090 healthy
     (18/18, 143 tools) — was NOT broken, only test names stale.
   - `TestCronJobs`: crontab is empty — all 41 cron entries consolidated into
     `hermes_scheduler.py` (`cron.py`-style `Job()` defs + `--daemon`). Rewrote to assert
     scheduler daemon is running (pgrep), critical `Job("name")` defined, scripts exist, and
     `data/scheduler_state.json` fresh (last_run within 48h with recent job success).
   - `TestN8n`: n8n is standalone webhook service, NOT a gateway MCP anymore. Container image has
     no Healthcheck. Now: POST `/webhook-test/ping` → expect 404 (proves webhook server alive);
     inspect container `.State.Status == running`.
   - `TestBackupIntegrity`: `verify_backups.sh`/`backup_volumes.sh` gone. Now checks current
     scripts: `kopia_backup.sh`, `db_backup.sh`, `backup_all.sh`, `sync_backup_remote.sh`, and
     scheduler `Job("backup_all"` / `Job("cloud_sync"`.
   - `TestHermesMemory`: `hermes-memory-mcp` container has no Healthcheck → check `.State.Status`.
   - `TestLogAggregation`: grafana on `:3001` (was `:3002`); loki datasource present.
   - `TestRateLimitTracker`: `/v1/rate-limits` endpoint removed from proxy. Observability now via
     proxy `/v1/status` → per-provider `health_probe` (healthy flag) + `circuit_breaker.state`.
   - `TestTokenJuice`: `/v1/token-juice` endpoint removed. Stats now nested in proxy `/v1/cache`
     → `{hits, misses, size, token_juice:{...}, short_circuit_size}`.

## Result
- `make test-regression`: 33 passed
- `make test-extended`: 78 passed
- Combined: **111 passed** (was 36 failed / 73 passed on fresh baseline)
- Committed `3c9612c` and pushed to `chaguli` (github.com/rmpmrepo1278/AgentHarness.git, branch `main`).

## Key architecture facts captured
- agentharness repo remote = `chaguli` → `AgentHarness.git`, branch `main` (do NOT push to origin).
- All scheduled jobs live in `~/.hermes/scripts/hermes_scheduler.py` (`Job("name", cmd, schedule)`),
  run via daemon: `python3 hermes_scheduler.py --daemon`. crontab is empty.
- MCP gateway: `localhost:8090`, 18 servers / 143 tools healthy. Server name prefixes:
  `infrastructure-*`, `system-*` (docker/network/homelab-ops), `global-chat(-mcp)`, `graphify-mcp`.
- Proxy `:8080` /v1 routes: `/health`, `/v1/models`, `/v1/status`, `/v1/cache` (GET+DELETE),
  `/v1/routing`, `/v1/chat/completions`, `/v1/messages`. NO `/v1/rate-limits`, NO `/v1/token-juice`.
- grafana :3001, loki :3100, promtail running.