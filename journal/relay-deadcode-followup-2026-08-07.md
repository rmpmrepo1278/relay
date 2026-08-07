# relay-deadcode-consolidation-2026-08-07

## Status: COMPLETE

### All four audit items delivered
- (agentharness) dead-code: 469b8bc — 27 fns + archived-stacks tree, 33 tests pass
- (home) hermes dead-code: 34 fns removed on-disk; f7f102e for the tracked n8n_tools.py
- telegram concat: collapsed 2 Markdown-path dups to send_telegram_markdown (audit was overstated; 4 distinct wrappers kept)
- doctor dedupe: a6f4efa — core/common/fs_checks.py shared primitives, 41 tests pass
- mcp_base: c17e1f5 — removed redundant byte-identical submodule copies in 4 packages + stale nested double-copy

### Open items re-evaluated
1. duckdns_puppeteer.py:14 f-string bug — RESOLVED: file was dead code (unreferenced in systemd/cron/repo; gitignored) with a syntax error that made it unimportable, which is exactly why CRG's dead-code pass could not see it. Deleted along with empty automation/ dir.
2. 3 divergent mcp_base variants (mcp-gateway, system-monitoring, codebase-memory) — NOT unified. These are INTENTIONALLY divergent:
   mcp-gateway uses socket-bind + register_signals param for host networking (bind_and_activate=False, manual sock); the canonical 257-line variant uses default HTTPServer binding + SSE/auth. docker-compose.mcp.merged.yml intentionally selects per-service variants via per-container volume mounts (e.g. mcp-gateway service mounts ./mcp-gateway/mcp_base.py, data-mgmt mounts its own). Forcing a single canonical onto live containers would change bind semantics → runtime regression + required container rebuilds while services down.
   RECOMMENDATION: leave intentional; if ever unified, do as a deliberate feature-flag redesign (MCPServer(start_mode=, enable_sse=, enable_auth=, bind_style=)) + coordinated container rebuild — NOT a blind dedup.

### Git-tracking allowlist (user-chosen option b)
gitignore allowlist negation + df90c9e baseline-tracking of 6 production entrypoints:
mind_loop.py, hermes_scheduler.py, n8n_bridge_server.py, system_health_check.py,
hermes_upgrade.py, gateway-preflight.sh. Secrets scan clean (env-var refs + homelab host paths only, consistent with existing tracked scripts).

### Verification
- agentharness: working tree clean, HEAD c17e1f5 on origin/main
- home: HEAD df90c9e on chaguli/main, upstream set
- Regression: test_regression_full + atomic_json + telegram_commands failures are PRE-EXISTING (fail on clean baseline); doctor/selftest/watchdog tests all pass

## Open question for follow-ups
- The 3 divergent mcp_base live containers could be unified only via a feature-flag redesign + planned downtime. Defer unless explicitly requested.
