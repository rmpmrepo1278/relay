# relay-deadcode-consolidation-2026-08-07

## Session goal
Fresh dead-code audit + consolidation pass across the homelab (AgentHarness repo +
`.hermes` scripts), scoped to four areas approved by the operator:
1. Remove CRG-flagged dead code (zero-caller symbols).
2. Consolidate duplicate send_telegram wrappers.
3. Dedupe core/doctor/troubleshoot.py vs core/resilience/selftest.py.
4. Unify duplicate mcp_base.py.

## Method
- Refreshed code-review-graph on both repos.
- Ran CRG `dead-code`; filtered to first-party symbols; delegated two read-only
  verification subagents (one per repo) to classify each candidate as
  DEAD / FALSE-POSITIVE (HTTP routes, plugin/register, cron, systemd, str-dispatch).
- For every confirmed-dead symbol, ran an additional `rg -l "\b\(sym\)\b"` sweep
  across the repo (excluding venv/venv/cache) **plus** systemd unit dirs, cron.d,
  and /var/spool/cron — the exact bug class that previously deleted a
  systemd-referenced script. Only symbols with truly zero references were removed.

## Results by repo

### /home/rohit/agentharness (AgentHarness)
- Removed 27 confirmed-dead functions/methods, incl:
  billing.py (orphaned module, never imported), budget/rate_limit_tracker/
  router/token_juice/llamacpp/provider unused methods, try_short_circuit
  (superseded by getattr-cache manip), watchdog/recover_all_stale_locks,
  metrics_emitter emit_runbook/emit_resource, gateway.mark_stale,
  autonomous_fixer/docker_inspect_health+count_recent_sessions,
  auto_fix_delegate/auto_rollback, homelab_monitor.update_config_backup.
- Deleted archived-stacks/old-mcp-servers/ (entire unreferenced legacy MCP tree,
  ~45 symbols / ~6.7k lines). Confirmed: zero references outside the tree itself;
  not mounted by any docker-compose or systemd unit.
- Committed 469b8bc — 33 regression tests pass.

NOTE: autonomous_fixer.py / auto_fix_delegate.py ARE referenced by the live
homelab-exec MCP handler + sync-registry.py — so only the dead FUNCTIONS were
removed, not the files.

### /home/rohit (.hermes scripts + plugins; AgentChaguli)
- Removed 33 confirmed-dead script/plugin functions (CostWrapper class,
  _send_telegram wrappers in career_engine/duckdns_puppeteer, dead methods in
  hermes_personality/unified_memory/loop_state/calendar_intelligence/etc).
- NOTE: these `.hermes/scripts*` paths are in the repo `.gitignore` (lines ~1066)
  and thus are NOT version-controlled; removals are on-disk only (the existing
  state of that tree). Only the one *tracked* file (n8n_tools.py) was committed
  as f7f102e.

### Consolidations
- Telegram wrappers: audit overstated — most files already call
  `from telegram_bridge import send_telegram` directly. Only 4 real wrappers
  remained, each with DISTINCT behavior (Markdown-default, 4096-truncation,
  emoji-prefix, config-load). Collapsed the two true Markdown-path dups
  (research_engine._send_telegram, digest.send_telegram) onto the bridge's
  existing `send_telegram_markdown`. The other 4 distinct wrappers kept
  (unifying would force a uniform signature losing behavior).
- Doctor dedupe: 3 byte-identical primitives shared by selftest/watchdog/troubleshoot
  (_pid_alive, stale-lock scan, dir-writable probe) extracted into
  `core/common/fs_checks.py`. selftest/watchdog/troubleshoot delegate to it.
  Public contracts preserved: selftest raises->dict, troubleshoot returns
  Optional[Issue] with fix_steps. Compiled + 41 tests pass. Committed a6f4efa.
- mcp_base: audit overstated (not 8 divergent-by-accident copies). Real state:
  `MCPServer` lives in each package's `__init__.py`; the sibling `mcp_base.py`
  was a byte-identical duplicate UNREFERENCED (all callers do
  `from mcp_base import MCPServer` -> __init__.py; zero `mcp_base.mcp_base`
  importers anywhere). Removed the dead submodule in 4 identical packages
  (global-chat, communication, data-management, infrastructure-services) and
  the stale double-nested `data-management/mcp_base/mcp_base/`.
  Left untouched (intentionally divergent): system-monitoring (auth/SSE
  variant), mcp-gateway (socket-bind variant), codebase-memory (single-file
  module). Import resolution re-verified for all 5 cleaned + 2 kept packages.
  Committed c17e1f5.
  NOTE: live containers must rebuild their images to lose the removed files —
  no Dockerfile changes were needed (they `COPY mcp_base <dir>`).

## Verification
- agentharness: compile OK on all edited modules; pytest relevant suites
  (doctor/troubleshoot/smoketest/validate/autofix, selftest, watchdog) = 44 passed.
- regression_full.py 81 failures confirmed PRE-EXISTING (fail on clean baseline
  with work stashed) — all live-endpoint/TLS/proxy tests unrelated to this work.
- mcp_base import resolution re-verified post-removal.

## Commits (agentharness main)
- 469b8bc  refactor: remove dead code (CRG-verified zero callers)
- a6f4efa  refactor: dedupe overlapping health-check primitives
- c17e1f5  refactor(mcp): remove redundant duplicate mcp_base.py files

## Notes for follow-ups / risk log
- `.hermes/scripts` gitignored → hermes dead-code deletions are on-disk, untracked.
  If these scripts should be versioned, fix the `.gitignore` entries first.
- duckdns_puppeteer.py line 14 has a PRE-EXISTING f-string SyntaxError
  (`{ .join(DOMAINS)}`) unrelated to this work — module is not imported anywhere
  (scheduler uses duckdns_update.sh). Flagged, not touched.
- The stale `docker-compose.mcp.merged.yml` mount `./ln/mcp_base.py:/mcp-base/...`
  references a path that does not exist in repo — that compose is not active.
