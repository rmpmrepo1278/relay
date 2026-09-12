# Graph Report - scripts  (2026-08-17)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1358 nodes · 2268 edges · 151 communities (85 shown, 66 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 40 edges (avg confidence: 0.6)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `f4c642ff`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- send_telegram
- archive/hermes_mcp_server.py
- n8n_bridge_server.py
- archive/proactive_engine.py
- archive/research_engine.py
- archive/career_engine.py
- archive/package_tracker.py
- archive/commitment_tracker.py
- narrative_memory.py
- archive/calendar_intelligence.py
- archive/gateway_guardian.py
- autonomous_self.py
- archive/insight_engine.py
- GraphRAG
- agent_orchestrator.py
- archive/hermes_mind.py
- archive/predictive_signals.py
- run_cycle
- archive/autonomous_fixer.py
- record
- homelab_graph.py
- archive/personal_research_digest.py
- run_exploration
- archive/email_intelligence.py
- archive/soul_overlay_gen.py
- Scheduler
- mind_loop.py
- handle_send
- temporal_kg.py
- personal_model.py
- archive/assess_idea.py
- GNAPAgent
- archive/unified_memory_mcp.py
- crg_status
- archive/self_prune.py
- homelab_research_pipeline.py
- _route_telegram_command
- archive/capsule_tracker.py
- archive/experiment_engine.py
- archive/feedback_loop.py
- archive/unified_cost_guard.py
- run_cmd
- archive/human_escalation.py
- archive/hc_uuids.sh
- create_plan
- execute_plan
- system_health_check.py
- archive/adaptive_thresholds.py
- archive/autonomous_work_session.py
- archive/homelab_troubleshooter.py
- archive/trip_planner.py
- _crg
- crg_impact
- archive/homelab_deployer.py
- archive/backup_all.py
- archive/capability_tracker.py
- archive/changelog_gen.py
- archive/claude_md_sync.py
- archive/config_snapshot.py
- ingest_report
- archive/homelab_discoverer.py
- archive/self_correction.py
- archive/task_executor.py
- _heal_load_state
- .check_auth
- archive/artifact_manager.py
- deduplicate_jsonl
- archive/learning_integrator.py
- reconcile_unanswered.py
- hermes_upgrade.py
- _NullSpan
- send_to_telegram
- check_command
- archive/llm_cost_logger.py
- archive/clean_task_queue.py
- archive/evaluator.py
- _collect_containers
- n.py
- split_entries
- hermes_consolidate.py
- _execute_with_repair
- _all_compose_files
- archive/dns_healthcheck.sh
- archive/init_collaborator_memory.sh
- archive/morning_briefing.py
- analyze_effectiveness
- _telegram_poller
- renew-local-certs.sh
- .verify_daily.sh
- archive/crg_register_repo.sh
- archive/hc_ping.sh
- archive/package_status_cron.sh
- _verify_capsule_fail_rate_dropped
- _verify_disk_space_freed
- _verify_memory_freed
- reauth_google.sh
- crg-git-hook.sh
- duckdns_update.sh
- gateway-preflight.sh
- handle_evening_briefing
- _telegram_get_updates
- get
- Request
- call_tool
- list_tools
- call_tool
- list_tools
- TextContent
- Tool
- Path
- call_tool
- list_tools
- Path
- TextContent
- Tool
- datetime
- Path
- Path
- Path
- Connection
- Path
- Any
- Path
- Any
- Path
- call_tool
- list_tools
- Connection
- Path
- Any
- get
- Request
- Path
- on_event
- datetime
- Path
- datetime
- Path
- Path
- Path
- call_tool
- list_tools
- Path
- TextContent
- Tool
- Connection
- Path

## God Nodes (most connected - your core abstractions)
1. `handler()` - 61 edges
2. `send_telegram()` - 21 edges
3. `run_cycle()` - 20 edges
4. `log()` - 16 edges
5. `record()` - 16 edges
6. `_run()` - 16 edges
7. `run_once()` - 16 edges
8. `GraphRAG` - 15 edges
9. `handle_gene()` - 14 edges
10. `_candidate_actions()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `dispatch()` --calls--> `handler()`  [INFERRED]
  agent_orchestrator.py → n8n_bridge_server.py
- `_call_tool()` --calls--> `handler()`  [INFERRED]
  archive/hermes_mcp_server.py → n8n_bridge_server.py
- `_crg_check()` --calls--> `crg_impact()`  [INFERRED]
  agent_orchestrator.py → archive/homelab_graph.py
- `run_cycle()` --calls--> `check_overdue()`  [INFERRED]
  mind_loop.py → archive/commitment_tracker.py
- `run_cycle()` --calls--> `get_upcoming()`  [INFERRED]
  mind_loop.py → archive/commitment_tracker.py

## Import Cycles
- None detected.

## Communities (151 total, 66 thin omitted)

### Community 0 - "send_telegram"
Cohesion: 0.06
Nodes (49): _dedup(), deliver(), Remove duplicate alert messages by source+msg hash., send_message(), extract_body(), main(), port_check(), api_hello() (+41 more)

### Community 1 - "archive/hermes_mcp_server.py"
Cohesion: 0.08
Nodes (32): cmd_approve(), cmd_decisions(), cmd_digest(), cmd_homelab_discover(), cmd_homelab_optimize(), cmd_homelab_pipeline(), cmd_homelab_report(), cmd_homelab_status() (+24 more)

### Community 2 - "n8n_bridge_server.py"
Cohesion: 0.10
Nodes (37): _cg_repos(), _gf(), _gf_explain(), _gf_path(), handle_backup_status(), handle_cert_check(), handle_deploy(), handle_disk_usage() (+29 more)

### Community 3 - "archive/proactive_engine.py"
Cohesion: 0.10
Nodes (35): _candidate_actions(), _capsule_fail_rate(), _content_hash(), escalate_to_human(), execute_plan(), get_predictions(), get_thresholds(), _health_score() (+27 more)

### Community 4 - "archive/research_engine.py"
Cohesion: 0.13
Nodes (34): approve_item(), cmd_approve(), cmd_clear_sent(), cmd_discover(), cmd_recommend(), cmd_status(), discover_all(), discover_github_trending() (+26 more)

### Community 5 - "archive/career_engine.py"
Cohesion: 0.12
Nodes (31): follow_up_stale(), get_pipeline_status(), _is_kept_url(), _is_us_linkedin(), job_search(), load_seen_urls(), load_state(), log() (+23 more)

### Community 6 - "archive/package_tracker.py"
Cohesion: 0.11
Nodes (31): _detect_order_refs(), _detect_status_from_text(), _extract_estimated_delivery(), _extract_tracking_numbers(), _fetch_carrier_status(), get_alerts(), _get_body_from_payload(), _get_gmail_service() (+23 more)

### Community 7 - "archive/commitment_tracker.py"
Cohesion: 0.11
Nodes (26): check_commitments(), load_commitments_from_data(), push_alert(), Load from data/commitments.json (new system) or commitments.json (old system)., main(), Scan a message for commitments and auto-register them. Returns: {…, scan_message(), add_commitment() (+18 more)

### Community 8 - "narrative_memory.py"
Cohesion: 0.11
Nodes (29): compute_insight_action_gap(), _cosine_sim(), _decay_old_episodes(), _derive_action(), _load_episodes(), _log(), mark_action_performed(), _ollama_embed() (+21 more)

### Community 9 - "archive/calendar_intelligence.py"
Cohesion: 0.12
Nodes (26): cache_events(), check_upcoming_reminders(), create_event(), fetch_events(), format_event(), generate_briefing_section(), get_calendar_service(), get_event_prep() (+18 more)

### Community 10 - "archive/gateway_guardian.py"
Cohesion: 0.15
Nodes (25): gateway_active(), main(), module_importable(), pre_snapshot_commit(), Return SHAs of recent auto-fix-snapshot commits., Get the commit just before the snapshot (the known-good state)., Hard reset to a known-good commit. DESTROYS working directory state., Reinstall hermes-agent from PyPI as last resort. (+17 more)

### Community 11 - "autonomous_self.py"
Cohesion: 0.15
Nodes (24): _actions_for_goal(), _calibration_bucket(), check_retry_budget(), consume_retry(), _default_state(), get_confidence(), _load_feedback(), _load_mind_loop_state() (+16 more)

### Community 12 - "archive/insight_engine.py"
Cohesion: 0.15
Nodes (23): generate_insights(), get_calendar_signals(), get_capsule_signals(), get_conversation_signals(), get_email_signals(), get_external_signals(), get_goal_signals(), get_health_signals() (+15 more)

### Community 13 - "GraphRAG"
Cohesion: 0.15
Nodes (10): GraphContext, GraphRAG, main(), Connection, Path, Build entity network around a given entity., Standalone entity extraction entry point. Runs via cron., Full GraphRAG query: extract entities, traverse graph, return context. (+2 more)

### Community 14 - "agent_orchestrator.py"
Cohesion: 0.13
Nodes (21): career_agent(), classify_task(), _crg_check(), decompose_plan(), dispatch(), dispatch_plan(), infra_agent(), knowledge_agent() (+13 more)

### Community 15 - "archive/hermes_mind.py"
Cohesion: 0.21
Nodes (21): auto_retire(), check_predictive(), check_telegram_approvals(), container_healthy(), get_container_logs(), _get_memory(), git_rollback_if_needed(), handle_gene() (+13 more)

### Community 16 - "archive/predictive_signals.py"
Cohesion: 0.15
Nodes (19): analyze_all_signals(), collect_current_signals(), compute_trend(), _ensure_history_dir(), get_predictions(), get_signal_history(), main(), predict_time_to_threshold() (+11 more)

### Community 17 - "run_cycle"
Cohesion: 0.13
Nodes (20): Reconcile sub-agent results from a dispatched plan: - Count successes/failures…, reconcile_and_surface(), anticipate(), append_insight(), evolve(), find_patterns(), log(), Trigger autonomous_fixer for sub-agent failures. (+12 more)

### Community 18 - "archive/autonomous_fixer.py"
Cohesion: 0.19
Nodes (17): analyze_capsule_patterns(), generate_lazy_dev(), load_playbook(), Return genes with failure counts > 3., Create lazy-dev playbook entry for problematic gene., Generate and store lazy-dev entries for failing genes., save_playbook(), sync_with_autonomous_fixer() (+9 more)

### Community 19 - "record"
Cohesion: 0.19
Nodes (14): _fmt(), load(), main(), _now(), Open a ledger entry. Returns the entry (with id) for later resolve()., Close an open entry with the actual outcome + evidence., record(), resolve() (+6 more)

### Community 20 - "homelab_graph.py"
Cohesion: 0.19
Nodes (18): crg_architecture(), _crg_args(), crg_dead_code(), crg_detect_changes(), crg_graph_health(), crg_query(), crg_repos(), crg_search() (+10 more)

### Community 21 - "archive/personal_research_digest.py"
Cohesion: 0.16
Nodes (18): format_digest(), gather_local_context(), generate_deep_research(), generate_digest(), load_config(), load_history(), Run GPT-Researcher on a query via the container. Modes: standard —…, Gather relevant local documents to enrich research context. Searches Paperless-… (+10 more)

### Community 22 - "run_exploration"
Cohesion: 0.18
Nodes (17): find_adjacent_topics(), find_cross_pollination(), get_arxiv_papers(), get_github_trending(), load_interest_profile(), load_seen(), _log_to_journal(), Get trending GitHub repos. (+9 more)

### Community 23 - "archive/email_intelligence.py"
Cohesion: 0.16
Nodes (17): categorize_email(), draft_email(), fetch_recent_emails(), format_digest(), get_gmail_service(), propose_email_reply(), push_to_inbox(), Categorize an email based on subject and snippet content. (+9 more)

### Community 24 - "archive/soul_overlay_gen.py"
Cohesion: 0.16
Nodes (17): generate_career(), generate_infra(), generate_knowledge(), generate_media(), generate_personal(), generate_research(), generate_travel(), main() (+9 more)

### Community 25 - "Scheduler"
Cohesion: 0.22
Nodes (6): define_jobs(), Job, main(), datetime, Schedule, Scheduler

### Community 26 - "mind_loop.py"
Cohesion: 0.15
Nodes (17): load_state(), observe_calendar(), observe_email(), observe_external_signals(), observe_health(), observe_telegram_history(), Display current mind state., Quick health snapshot. (+9 more)

### Community 27 - "handle_send"
Cohesion: 0.13
Nodes (18): _clear_proposal(), handle_send(), handle_service_restart(), handle_skip(), handle_telegram_send(), _heal_notify_paused(), _heal_save_state(), _load_proposal() (+10 more)

### Community 28 - "temporal_kg.py"
Cohesion: 0.22
Nodes (17): add_decision(), ensure_decisions_table(), get_db(), get_stats(), get_timeline(), ingest_capsules(), ingest_health_dashboards(), main() (+9 more)

### Community 29 - "personal_model.py"
Cohesion: 0.20
Nodes (16): decay_and_reprioritise(), _default_state(), _extract_unspoken_needs(), _extract_values(), generate_life_goals(), get_context_signals(), _load_state(), _log() (+8 more)

### Community 30 - "archive/assess_idea.py"
Cohesion: 0.18
Nodes (15): assess_homelab_applicability(), _complements(), crg_assess(), _estimate_token_savings(), fetch_repo_info(), _get_running_services(), graphify_assess(), main() (+7 more)

### Community 31 - "GNAPAgent"
Cohesion: 0.20
Nodes (5): AgentManifest, Capability, GNAPAgent, main(), Path

### Community 32 - "archive/unified_memory_mcp.py"
Cohesion: 0.24
Nodes (14): _call_tool(), call_tool, call_tool(), exec_sql(), handle_query(), handle_recall(), handle_stats(), handle_store() (+6 more)

### Community 33 - "crg_status"
Cohesion: 0.19
Nodes (13): evaluate(), evaluate_candidate(), get_current_stack(), get_resource_usage(), load_state(), homelab_evaluator.py — Evaluates discovered candidates for deployment Reads…, Return list of Docker images currently running, Return current resource usage summary (+5 more)

### Community 34 - "archive/self_prune.py"
Cohesion: 0.22
Nodes (14): import_blockers(), main(), _module_names(), Path, Candidate import names for a file, e.g. scripts/syslog_emit.py ->…, Return list of live files that import the given file's module., archive_dead_script(), disable_job_in_scheduler() (+6 more)

### Community 35 - "homelab_research_pipeline.py"
Cohesion: 0.23
Nodes (15): assess_item(), pipeline(), Verify a claim against actual system state. Returns (verified, evidence)., Verify that pipeline results are real, not hallucinated., Progress updates to Telegram (gated — off by default to keep inbox actionable)., Run daily_research.py to discover new repos., Run research_engine.py discover + recommend., Run CRG/graphify assessment on a discovered item. (+7 more)

### Community 36 - "_route_telegram_command"
Cohesion: 0.13
Nodes (16): _call(), _first_word(), _fmt(), handle_cmd(), handle_morning_briefing(), _help_text(), _logs(), Push an escalation-style notification to the Telegram channel. (+8 more)

### Community 37 - "archive/capsule_tracker.py"
Cohesion: 0.24
Nodes (13): check_target_health(), ensure_dir(), get_stats(), load_capsules(), main(), Best-effort re-check of a target's health. Returns 'success'|'fail'|None., Re-check target health and append verification to the latest matching record., Record a Capsule outcome. (+5 more)

### Community 38 - "archive/experiment_engine.py"
Cohesion: 0.23
Nodes (13): execute_experiment(), get_experiment_stats(), _load_experiments(), main(), _maybe_promote_winner(), Record experiment outcome (success/fail/partial)., Check if a variant has enough evidence to be promoted as default., Run an experiment for the given action. (+5 more)

### Community 39 - "archive/feedback_loop.py"
Cohesion: 0.20
Nodes (14): check_action_outcomes(), generate_adjustments(), generate_report(), load_data(), load_feedback(), log_suggestion(), Analyze patterns and recommend adjustments to proactive behavior., Record an action in the decision ledger (proactive suggestion or command). (+6 more)

### Community 40 - "archive/unified_cost_guard.py"
Cohesion: 0.25
Nodes (14): check(), check_billing(), check_claude_code(), check_hermes_proxy(), get_openrouter_key(), load_json(), log(), Verify Hermes proxy config uses free providers. (+6 more)

### Community 41 - "run_cmd"
Cohesion: 0.23
Nodes (13): run_cmd(), get_docker_stats(), get_system_metrics(), optimize(), optimize_alert_thresholds(), optimize_log_retention(), optimize_resource_limits(), homelab_optimizer.py — Self-optimization engine Tunes resource limits,… (+5 more)

### Community 42 - "archive/human_escalation.py"
Cohesion: 0.25
Nodes (13): _check_budget(), escalate_to_human(), get_escalation_stats(), handle_human_response(), _load_budget(), main(), Send escalation to human via Telegram., Process human response to escalation. Returns decision. (+5 more)

### Community 43 - "archive/hc_uuids.sh"
Cohesion: 0.15
Nodes (12): HC_UUID_AUTONOMOUS_FIXER, HC_UUID_BACKUP_VOLUMES, HC_UUID_CONSOLIDATED_HEALTH, HC_UUID_CVE_SCAN, HC_UUID_DB_BACKUP, HC_UUID_DOCKER_GHOST_CHECK, HC_UUID_HEALTH_DASHBOARD, HC_UUID_MORNING_PIPELINE (+4 more)

### Community 44 - "create_plan"
Cohesion: 0.17
Nodes (12): _check_confidence(), create_plan(), _diagnose_from_insight(), _propose_authoring_action(), Convert insights + anticipations + personal-model goals + narrative-memory gap-…, Check calibrated confidence for an action type via autonomous_self., Turn an insight into a diagnostic command., Close the insight→done loop by proposing an authoring action (email reply,… (+4 more)

### Community 45 - "execute_plan"
Cohesion: 0.17
Nodes (12): compose_morning_briefing(), execute_plan(), Compose a morning briefing message., Add a task to the persistent task queue., Execute the planned actions with guardrails, quality tracking, inline…, Record an event in episodic memory., Record action outcome for self-model confidence calibration., Register an action for self-correction verification. (+4 more)

### Community 46 - "system_health_check.py"
Cohesion: 0.30
Nodes (11): check_port(), check_process(), check_systemd(), check_telegram_gateway(), load_registry(), load_state(), main(), Service list from the inventory. Prefer the fresh generated file… (+3 more)

### Community 47 - "archive/adaptive_thresholds.py"
Cohesion: 0.31
Nodes (10): adapt_thresholds(), analyze_outcomes(), get_thresholds(), ledger_load(), _load_thresholds(), main(), Adapt thresholds based on historical outcomes., Get current adaptive thresholds (for use by proactive_engine). (+2 more)

### Community 48 - "archive/autonomous_work_session.py"
Cohesion: 0.38
Nodes (10): commitment_check(), health_snapshot(), log(), main(), Quick health snapshot., Check for overdue commitments., Review pending tasks., run_cmd() (+2 more)

### Community 49 - "archive/homelab_troubleshooter.py"
Cohesion: 0.35
Nodes (10): check_container(), cmd_exclude_add(), cmd_exclude_list(), cmd_exclude_remove(), diagnose_container(), diagnose_cycle(), get_all_containers(), load_excluded() (+2 more)

### Community 50 - "archive/trip_planner.py"
Cohesion: 0.45
Nodes (10): cmd_countdown(), cmd_itinerary(), cmd_status(), cmd_task_add(), cmd_tasks(), cmd_today(), _load_tasks(), _load_trip() (+2 more)

### Community 51 - "_crg"
Cohesion: 0.27
Nodes (11): _cg_arch(), _cg_dead(), _cg_flows(), _cg_impact(), _cg_query(), _cg_search(), _cg_status(), _clean_lines() (+3 more)

### Community 52 - "crg_impact"
Cohesion: 0.29
Nodes (9): assess_impact(), atomic_json_write(), main(), Path, Assess the potential impact of a repository, Run GitHub API search, Write JSON atomically: dump to temp file in same dir, then rename. Prevents…, run_search() (+1 more)

### Community 53 - "archive/homelab_deployer.py"
Cohesion: 0.31
Nodes (9): backup_compose(), deploy(), deploy_mcp_server(), log_deploy(), homelab_deployer.py — Auto-deploys evaluated candidates Handles: MCP server…, Add MCP server to opencode config, Run basic health check after deployment, verify_after_deploy() (+1 more)

### Community 54 - "archive/backup_all.py"
Cohesion: 0.44
Nodes (8): db_dumps(), kopia_dirs(), kopia_volumes(), main(), run(), running_containers(), step(), sudo_test()

### Community 55 - "archive/capability_tracker.py"
Cohesion: 0.33
Nodes (8): append_history(), build_report(), Parse scheduler script to extract job metadata (description, tags, enabled)., Append a time-stamped snapshot of all job states to the history log., Analyze history and build a capability report., read_job_definitions(), read_scheduler_state(), track()

### Community 56 - "archive/changelog_gen.py"
Cohesion: 0.39
Nodes (8): build_changelog(), extract_narrative(), format_capsules(), git_log(), main(), parse_capsules(), Extract hand-written narrative section between markers., run()

### Community 57 - "archive/claude_md_sync.py"
Cohesion: 0.39
Nodes (8): gen_containers(), gen_cron_jobs(), gen_storage_live(), gen_system_stats(), gen_systemd_live(), _replace_named(), run(), sync()

### Community 58 - "archive/config_snapshot.py"
Cohesion: 0.39
Nodes (7): capture(), diff(), _get_crontab(), _get_disk(), _get_docker_ps(), _get_model_config(), save()

### Community 59 - "ingest_report"
Cohesion: 0.39
Nodes (7): extract_entities(), ingest_report(), main(), Path, Extract key entities from research text for KG ingestion., Ingest a single report into temporal_kg., run()

### Community 60 - "archive/homelab_discoverer.py"
Cohesion: 0.48
Nodes (6): discover(), fetch_json(), load_state(), homelab_discoverer.py — Autonomous discovery engine Scans GitHub trending,…, save_state(), score_repo()

### Community 61 - "archive/self_correction.py"
Cohesion: 0.43
Nodes (6): check_scheduler_health(), check_task_results(), push_alert(), Check recently completed tasks — did they actually resolve the issue?, Check if most scheduler jobs are succeeding., run()

### Community 62 - "archive/task_executor.py"
Cohesion: 0.52
Nodes (6): execute_research_task(), execute_task(), load_queue(), push_alert(), run(), save_queue()

### Community 63 - "_heal_load_state"
Cohesion: 0.29
Nodes (7): handle_all_services_status(), handle_service_heal_status(), _heal_load_state(), _load_json(), Return services currently paused by auto-heal de-escalation., _sys_proactive(), _sys_queue()

### Community 65 - "archive/artifact_manager.py"
Cohesion: 0.47
Nodes (5): format_artifact_report(), init(), list_artifacts(), Generate a daily markdown report from pipeline state, save_artifact()

### Community 66 - "deduplicate_jsonl"
Cohesion: 0.33
Nodes (5): deduplicate_jsonl(), prune_capsules(), Path, Remove duplicate entries based on key combo. Return count removed., Keep only last N capsule entries.

### Community 67 - "archive/learning_integrator.py"
Cohesion: 0.47
Nodes (5): analyze_session_patterns(), main(), Find common failure patterns in logs., Generate improvement suggestions for SOUL.md., suggest_improvements()

### Community 68 - "reconcile_unanswered.py"
Cohesion: 0.60
Nodes (5): detect_unanswered(), load_token(), main(), run_agent(), send_telegram()

### Community 69 - "hermes_upgrade.py"
Cohesion: 0.73
Nodes (5): log(), main(), patch_goal_judge(), patch_sitecustomize(), run()

### Community 71 - "send_to_telegram"
Cohesion: 0.33
Nodes (6): Send a sub-agent proposal to Telegram with confirm/skip hint., Send a message to Telegram via bridge, with deduplication., Record an action in the feedback loop for outcome tracking., _record_feedback(), _send_proposal_telegram(), send_to_telegram()

### Community 72 - "check_command"
Cohesion: 0.50
Nodes (4): check_command(), Check if command is destructive. Returns (is_safe, reason)., Run command with guard., run_guarded()

### Community 73 - "archive/llm_cost_logger.py"
Cohesion: 0.60
Nodes (3): get_summary(), init(), log_call()

### Community 74 - "archive/clean_task_queue.py"
Cohesion: 0.83
Nodes (3): clean(), _parse_ts(), datetime

### Community 75 - "archive/evaluator.py"
Cohesion: 0.83
Nodes (3): evaluate(), init(), trend()

### Community 76 - "_collect_containers"
Cohesion: 0.67
Nodes (3): _collect_containers(), main(), Collect container status from Docker.

### Community 77 - "n.py"
Cohesion: 0.83
Nodes (3): _assess(), _install(), main()

### Community 78 - "split_entries"
Cohesion: 0.67
Nodes (3): ingest(), Split a markdown doc into [(heading, body)] sections., split_entries()

### Community 79 - "hermes_consolidate.py"
Cohesion: 0.83
Nodes (3): attach_all(), count(), migrate()

### Community 80 - "_execute_with_repair"
Cohesion: 0.50
Nodes (4): _execute_with_repair(), Run a command; on failure, attempt a fallback diagnostic., Suggest a fallback command for a failed one based on heuristics., _repair_command()

### Community 81 - "_all_compose_files"
Cohesion: 0.67
Nodes (3): _all_compose_files(), main(), Return {path: sha256} for every .yml/.yaml file we should watch.

### Community 86 - "_telegram_poller"
Cohesion: 0.67
Nodes (3): main(), Background thread: polls Telegram for incoming commands and routes them., _telegram_poller()

## Knowledge Gaps
- **24 isolated node(s):** `crg-git-hook.sh script`, `duckdns_update.sh script`, `gateway-preflight.sh script`, `HC_UUID_AUTONOMOUS_FIXER`, `HC_UUID_BACKUP_VOLUMES` (+19 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **66 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `handler()` connect `n8n_bridge_server.py` to `archive/unified_memory_mcp.py`, `.check_auth`, `_route_telegram_command`, `create_plan`, `agent_orchestrator.py`, `_crg`, `handle_send`, `_heal_load_state`?**
  _High betweenness centrality (0.109) - this node is a cross-community bridge._
- **Why does `send_to_telegram()` connect `send_to_telegram` to `run_cycle`, `archive/human_escalation.py`, `mind_loop.py`, `execute_plan`?**
  _High betweenness centrality (0.104) - this node is a cross-community bridge._
- **Why does `crg_impact()` connect `crg_impact` to `crg_status`, `archive/research_engine.py`, `run_cmd`, `agent_orchestrator.py`, `homelab_graph.py`, `archive/homelab_deployer.py`?**
  _High betweenness centrality (0.104) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `handler()` (e.g. with `dispatch()` and `_call_tool()`) actually correct?**
  _`handler()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `run_cycle()` (e.g. with `check_overdue()` and `get_upcoming()`) actually correct?**
  _`run_cycle()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `crg-git-hook.sh script`, `duckdns_update.sh script`, `gateway-preflight.sh script` to the rest of the system?**
  _24 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `send_telegram` be split into smaller, more focused modules?**
  _Cohesion score 0.06298701298701298 - nodes in this community are weakly interconnected._