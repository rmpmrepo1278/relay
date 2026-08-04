# Relay — homelab_graph.py Upgraded to Multi-Repo CRG (2026-08-04)

## What shipped
- **homelab_graph.py** (`~/.hermes/scripts/homelab_graph.py`) upgraded from single-repo to multi-repo. Previously every CRG call auto-detected from cwd (hermes-scripts) — the wrapper never passed `--repo`, so blast-radius/dead-code always pointed at the wrong graph.
  - All CRG functions (`crg_status`, `crg_impact`, `crg_search`, `crg_dead_code`, `crg_architecture`, `crg_query`, `crg_detect_changes`) now accept an optional `repo=` arg (registry alias like `agentharness`, `hermes-agent`, `career-ops`, or absolute path), resolved via `~/.code-review-graph/registry.json`.
  - Added `crg_repos()` (lists registered repos) and `crg_graph_health(stale_hours=48)` (flags repos whose graph is empty or stale).
  - **Backward compatible**: all 8 existing daily-script callers (deployer, discoverer, evaluator, optimizer, reporter, troubleshooter, research_engine, daily_research) still work unchanged.
- **system_doctor.py** — `doctor()` now appends an action for each stale/empty repo graph via `check_graph_health()` (guarded local import + `.format()` to avoid nested-quote f-string bug). Verified clean run, exit 0.
- **homelab_deployer.py** — already consumed `crg_impact` at deploy time; now benefits automatically from multi-repo resolution.

## Registry (6 repos)
agentharness, hermes-scripts (`~/.hermes`), hermes-agent, career-ops, collaborator-memory, home. All resolve; watch.toml watches all 6; bridge :9199 serves per-repo via `/code-graph/*?repo=<alias>`.

## Graph state
home 14776n/80083e · hermes-scripts 1137n/13754e · hermes-agent 827n · career-ops 423n. collaborator-memory = 0 nodes (journal/markdown only — expected, flagged as healthy-by-design).

## Verification
`python3 homelab_graph.py health` → flags only collaborator-memory (0 nodes). Per-repo `status --repo hermes-agent` returns 827n/11308e. Module imports cleanly; 8 original functions present plus 2 new.

## Added later — bridge auth fix
`AUTH_KEY = os.environ.get("BRIDGE_AUTH_KEY")` had **no fallback default**, so it was `None` while every local caller (telegram_bridge, hermes-bridge plugin, research pipeline) relies on the shared default `"default-key-change-me"` via `BRIDGE_AUTH_KEY`. Result: all auth-gated CRG endpoints (dead-code, search, query, impact, architecture) were silently locked out with 401 "unauthorized". Restored matching default and added `/code-graph/repos` to the no-auth GET set (localhost-only, alias→path only). Verified E2E: status (per-repo), dead-code (57 hermes-agent / 189 default), search (FTS 13 matches), `/cmd /graph` + `/cmd /deadcode` routes. graphify-mcp stdio initialize returns serverInfo (0.9.32); code-review-graph MCP unaffected.

## Commits (on `~/.hermes`, chaguli)
- `82380be` Wire homelab_graph.py to multi-repo CRG registry
- `14d980a` surface stale/empty CRG graphs as sessions in system_doctor
- `e346ed0` fix(bridge): restore BRIDGE_AUTH_KEY default + expose repo aliases

## Notes
- Cleaned up a diverged collaborator-memory: local WIP was stale (superseded by origin's richer journal), reset to origin/main rather than force-pushing conflicts.
- Retired redundant `crg_helper.py` approach in favor of upgrading the canonical `homelab_graph.py` wrapper (nothing else imported crg_helper).
## Audit: redundant/dead code removal (2026-08-04)

### Findings
- CRG dead-code scan returned 101 hermes-owned symbols, but **all 101 are used** via dynamic dispatch (decorator registration, plugin loaders, dict routing). CRG has a high false-positive rate for this codebase.
- `homelab_research_pipeline.py` — zero callers (no imports, no cron, no scheduler). **Removed.**
- `crg_helper.py` — redundant with `homelab_graph.py` (nothing imports it). **Removed.**
- `homelab_graph.py:repo_graph_path()` — dead code within homelab_graph.py (0 callers). **Removed.**
- Backup clutter: 9 files removed (`.bak`, `.corrupt.bak`, `.bak2`, `.bak3`, `.corrupt`).
- `run_cmd` duplicated 6× across scripts and `_run` duplicated 5× — noted as consolidation candidates for a future refactor.

### Removed files
- `scripts/crg_helper.py`
- `scripts/homelab_research_pipeline.py`
- `scripts/homelab_graph.py.bak-multirepo`
- `scripts/homelab_graph.py.bak-reposauth`
- `scripts/n8n_bridge_server.py.bak-multirepo`
- `scripts/n8n_bridge_server.py.bak-reposauth`
- `config.yaml.bak-fix3-1785863045`
- `config.yaml.bak2`
- `config.yaml.corrupt.20260804-100435.bak`
- `topic_routes.json.bak3`
- `state/curious_seen.corrupt`
- `homelab_graph.py:repo_graph_path()` function (lines 162-168)

### Commit
- `aad0b78` audit: remove redundant crg_helper, dead homelab_research_pipeline, backup clutter, repo_graph_path
