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

## Commits (on `~/.hermes`, chaguli)
- `82380be` Wire homelab_graph.py to multi-repo CRG registry
- `14d980a` surface stale/empty CRG graphs as sessions in system_doctor

## Notes
- Cleaned up a diverged collaborator-memory: local WIP was stale (superseded by origin's richer journal), reset to origin/main rather than force-pushing conflicts.
- Retired redundant `crg_helper.py` approach in favor of upgrading the canonical `homelab_graph.py` wrapper (nothing else imported crg_helper).