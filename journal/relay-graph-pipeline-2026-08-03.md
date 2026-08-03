# Relay — CRG/Graphify Wired into Homelab Pipeline (2026-08-03)

## What shipped
- **homelab_graph.py helper module** created at `~/.hermes/scripts/homelab_graph.py` — wraps `code-review-graph` and `graphify` CLI into Python functions (`crg_status`, `crg_impact`, `crg_architecture`, `crg_search`, `crg_query`, `crg_dead_code`, `graphify_explain`, `graphify_path`, `graphify_diagnose`). All functions return structured dicts, not raw text.
- **homelab_evaluator.py** — CRG blast-radius check added to `evaluate_candidate()`. Candidates with high impact (>10 affected files) are downgraded to `wait` instead of `deploy`. Graph stats (nodes/edges) printed during evaluation runs.
- **homelab_deployer.py** — CRG blast-radius check added before service deploy. High-impact deploys are flagged (`status: "flagged"`) instead of blindly proceeding.
- **homelab_discoverer.py** — CRG architecture overview fetched for MCP server discoveries; graph stats included in discovery run output.
- **homelab_optimizer.py** — CRG impact analysis included in resource limit suggestions; graph stats printed during optimization runs.
- **homelab_troubleshooter.py** — CRG dependency query added to `diagnose_container()` for failed containers; graph dependents appended to diagnosis output.
- **homelab_reporter.py** — CRG graph stats (nodes/edges/files/last_updated) added as a "Code Graph" section in structured reports.

## Commit
- `a8764a8` on `chaguli/master` (pushed) — 7 files changed, 191 insertions, 1 deletion

## Verification
- All 6 modified scripts pass `ast.parse()` syntax check.
- `homelab_graph.py` import verified working on homelab.
- CRG graph has 1148 nodes, 13637 edges, 155 files across 3 registered repos.

## Gotcha notes
- CRG graph is for `/home/rohit/.hermes` (hermes-scripts) by default; `/home/rohit/agentharness` and `/home/rohit/.hermes/hermes-agent` also registered.
- `crg_impact()` returns `{"impact": "high|medium|low", "affected_files": N, "affected_components": [...]}`.
- `crg_status()` returns parsed dict with `nodes`, `edges`, `files`, `languages`, `last_updated`, `built_on_branch`, `built_at_commit`.
