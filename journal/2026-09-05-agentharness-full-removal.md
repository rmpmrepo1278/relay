# 2026-09-05 — Full AgentHarness removal completed

## What happened
Completed the "Full AgentHarness removal" (2nd wave) the night after the watchdog fix. The 1st wave (Phases 1–7) removed consumers/aliases/units/repo and pushed history to GitHub (`b28c225`). This 2nd wave swept every remaining LIVE reference to the deleted `/home/rohit/agentharness` path and cleaned 4 dead/red system states.

## Expanded cleanup (wave 2) — done
- **Alerts/inbox transport** repointed from `~/agentharness/data/alerts_inbox.jsonl` → `~/.hermes/data/alerts_inbox.jsonl` in 8 consumers (alerts_delivery, commitment_executor, email_intelligence, self_correction, task_executor, human_overrides, proactive/proactive_orchestrator, lib/council_vote). Writers mkdir parents; `human_overrides._alerts_file()` simplified (dead primary path removed). mind_loop already used the hermes path.
- **crg tooling**: `crg_context.py` alias removed, `crg-git-hook.sh` case removed, `homelab_graph.py` `_DEFAULT_REPO` → `~/.hermes`, `n8n_bridge_server.py` `_CRG_DEFAULT_REPO` → `~/.hermes`.
- **Scan scripts**: doc_drift_check `a` fallback → `~/.hermes/scripts`; debloat.sh (find/for/step-6); hermes_mind repo list; import_safety SCAN_ROOTS; research_engine keyword; rotate_logs.sh dirs; self_evolution log list; self_prune fallback rglob.
- **Exec/econ**: insight_engine + mind_loop no longer shell out to deleted `health_dashboard.py` (both read `health_signals.json` now); unified_cost_guard env_file → `~/.hermes/.env`; sync_compose_changes COMPOSE_DIRS + HOOK (→ nonexistent hook path, guarded); consolidate_homelab (removed MCP_COMPOSE block); import_ollama_models.sh LOG. Deleted: `~/scripts/update_proxy.py`, `~/scripts/test_pii.py`.
- **OpenJarvis**: config.toml `default_model` ×2 → `haiku-4.5` (api_base was already hop `:8083`); header comments; plugin.yaml + tools.py docstrings → "hop LLM gateway"; patches README.
- **Claude settings** (`~/.config/claude/settings.json`): base_url 8080→8083, model `agentharness-proxy`→`haiku-4.5`.
- **Units**: removed `dashboard.service` (dead AgentHarness dashboard; :9100 is the hermes-dashboard container), `code-review-graph.service` (old, agentharness repo), `crg-daemon.service` (failed since Sep 3, registry missing), `homelab-backup.timer` + `.service.bak` (service was missing → broken legacy timer; NOTE volume backup automation is now unmanaged). Removed `/etc/systemd/system/tokenjuice-hop.service.bak-preagentproxy` + `/tmp/tokenjuice-hop.service`.
- **Re-created** `code-review-graph.service` (user) scoped to `--repo /home/rohit/.hermes` → MCP at 127.0.0.1:8095 active again (opencode.jsonc + claude allow-list keep working).
- Removed desktop-commander MCP entries from `.config/opencode/{opencode.jsonc,mcp.json}` (server was in the deleted dir).
- Removed `~/.config/logrotate/agentharness-data`.

## Verification (all green)
- py_compile all 21+2 edited .py; bash -n all 4 .sh.
- hop `/health` ok; `haiku-4.5` chat → returned `cohere/north-mini-code:free` "HOP_OK" (chain OK).
- jarvis via openjarvis :1377 → "JARVIS_OK" (end-to-end hop).
- openjarvis.service (system) active; CRG user service active; hermes-scheduler active (0 agentharness refs); watchdog running with `sudo -n systemctl restart`.
- Residual live refs in scripts/config: ONLY `~/.config/logrotate/status` (logrotate bookkeeping, inert). Data dirs (sessions/state/request dumps) intentionally retain historical text.

## Notes / follow-ups
- **Volume/DB backup automation gap**: homelab-backup.timer was already broken (service file absent); kopia scripts lived in the deleted dir. Daily docker volume backups currently have no runner — needs re-establishing (user sign-off).
- `~/.code-review-graph/registry.json` doesn't exist in this deployment → crg alias resolution in `homelab_graph.py` returns None and relies on cwd auto-detection (unchanged behavior; crg-daemon disable is consistent).
- OpenJarvis v1.0.3 available (`jarvis self-update`) — not applied (persistent jarvis found; patch README rewired to hop anyway).
- Backups taken: `~/agentproxy-removal2-pre.tar.gz` on box; local worktree at `/var/folders/…/opencode/agentharness-removal/` (edited copies + original tar).
- Ask user: (1) delete GitHub `rmpmrepo1278/AgentHarness.git` (only remaining history copy)? (2) re-establish volume backups?