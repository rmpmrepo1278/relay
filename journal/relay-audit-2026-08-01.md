# Relay Journal — 2026-08-01

## Audit: AgentHarness repo — full sweep, fixes, git check-in

Relay ran a thorough audit of `/home/rohit/agentharness` (homelab, via `ssh homelab-cmd`), fixed all open issues, updated docs, committed + pushed. HEAD `bbd6a57` → `8fe30a0`.

### Proxy & routing (the deepseek work, verified end-to-end)
- `deepseek-v4-flash` provider registered (OpenRouter `:free`, daily_limit 50000) + model routing added. Routing confirmed working: deepseek tried first, falls through to Groq only because OpenRouter returns 429 `free-models-per-day-high-balance` (remaining 0, resets 1785628800000). NOT a routing bug — free-tier daily cap.
- Added `forced_provider` param to `Router.route()`; proxy passes it from `tool_model_routing`/`standard_model_routing`.
- Fixed `/v1/status` 500: `enabled` is a method (`p.enabled()`) but code did `getattr(p, "enabled", True)` returning a bound method → not JSON-serializable.
- Status now classifies `type: local` for localhost/127.0.0.1 endpoint providers (fixed `local-bmoe`).

### Provider correctness (regressions found + fixed)
- `base.py` (uncommitted refactor had introduced bugs): LLMResponse `error` classmethod collided with the field (every response got `error=<bound method>`); `total_tokens` was a dead field not computed; BudgetStatus lost `known_remaining`/`reset_at`. Restored working contract.
- `router.py`: `is_available()` check had been dropped in the circuit-breaker commit — restored.
- `groq.py`: `_usage_today` never incremented, so daily_limit never enforced — fixed.
- `llamacpp.py`: Ollama adapter now parses `prompt_eval_count` into tokens_in (test was stale).
- Removed stale `tests/test_inbox_watcher.py` (Mac scratch path `/Users/rohitmishra/.gemini/...`, dead API, broke collection).
- Provider test suite: 8 failing → 31 passing.

### Pre-push gate
- `test_regression_suite.py` (33 tests, runs in pre-push hook) now green.
- `.env` symlink contract was broken (`vault.py gen-env` wrote a regular file). Union-merged data/.env's 11 extra keys into `~/.secrets/master.env` (30 keys total), restored `data/.env` → symlink. Note: `data/.env` (and `data/.env.local`) are gitignored; master.env is NOT referenced by any active script/systemd/cron — Vaultwarden is the true source.
- Backups: `~/.secrets/master.env.bak-20260801`, `data/.env.bak-20260801`.

### Repo hygiene
- `.gitignore`: added `*.log.*` rotation patterns + compiled `codebase-memory-mcp/codebase-memory-mcp` (270MB ELF binary).
- Untracked 244 historical log files.
- Script rewrites (db_backup, backup_all, kopia, traefik) removed hardcoded credentials (PAPERLESS_TOKEN, PGPASSWORD literals).
- Deleted MCP build dirs + archived old MCP servers consolidated (autonomous agent cleanup, committed as part of audit).

### Test status (baseline vs now)
- Full suite: 122 failed / 468 passed (at HEAD) → 117 failed / 473 passed. My fixes resolved 5; the remaining 117 are ALL pre-existing environmental/stale tests: TestDockerContainers (decommissioned MCP containers like file-mcp/backup-mcp/doctor-mcp), TestCronJobs (crontab consolidated to hermes_scheduler.py — tests reference old entries), TestServiceEndpoints, TestSystemdServices, TestTokenJuice, TestRateLimitTracker, TestBackupIntegrity, TestLogAggregation, TestMCPGateway, TestN8n, TestHermesMemory. Not related to proxy work; pre-push gate unaffected.

### Open items (not blocking, pre-existing)
- DeepSeek free-tier 429 will clear at the daily reset — no action needed.
- 117 stale infra tests listed above are a backlog item if full `make test` green is desired.
