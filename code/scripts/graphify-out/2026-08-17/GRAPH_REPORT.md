# Graph Report - scripts  (2026-08-02)

## Corpus Check
- 154 files · ~103,782 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1755 nodes · 2941 edges · 145 communities (118 shown, 27 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 43 edges (avg confidence: 0.59)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a431540e`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- gateway_guardian.py
- unused-20260726/hermes_mcp_server.py
- UnifiedMemory
- proactive_engine.py
- handler
- research_engine.py
- handler
- commitment_tracker.py
- hermes_mcp_server.py
- package_tracker.py
- pre-n8n-reduce-20260725/homelab_reporter.py
- calendar_intelligence.py
- career_engine.py
- career_autonomous.py
- insight_engine.py
- HermesMemory
- hermes_mind.py
- GraphRAG
- ace_playbook.py
- LoopState
- predictive_signals.py
- pre-n8n-reduce-20260725/homelab_troubleshooter.py
- bmoe_server.py
- curious_explorer.py
- SkillRegistry
- send_telegram
- Scheduler
- mind_loop.py
- soul_overlay_gen.py
- hc_uuids.sh
- GNAPAgent
- Guardrails
- temporal_kg.py
- pre-n8n-reduce-20260725/system_doctor.py
- decision_ledger.py
- run_cycle
- personal_research_digest.py
- QualityTracker
- hermes_health.py
- research_consumer.py
- skill_library.py
- record
- persona_engine.py
- unused-20260726/unified_cost_guard.py
- capsule_tracker.py
- experiment_engine.py
- feedback_loop.py
- send_to_telegram
- unified_cost_guard.py
- process_conversations
- Span
- homelab_optimizer.py
- install_manager.py
- unused-20260726/unified_memory_mcp.py
- proactive_orchestrator.py
- unified_memory_mcp.py
- autonomous_fixer.py
- email_intelligence.py
- homelab_troubleshooter.py
- adaptive_thresholds.py
- autonomous_work_session.py
- homelab_deployer.py
- homelab_evaluator.py
- system_doctor.py
- trip_planner.py
- backup_health.py
- pre-n8n-reduce-20260725/system_health_check.py
- self_prune.py
- system_health_check.py
- sync_with_autonomous_fixer
- n8n_mcp.py
- pii_classifier.py
- review_traces.py
- backup_all.py
- capability_tracker.py
- changelog_gen.py
- claude_md_sync.py
- config_snapshot.py
- daily_research.py
- local_anthropic_proxy.py
- RunLog
- interest_model.py
- pre-n8n-reduce-20260725/task_executor.py
- homelab_orchestrator.py
- unused-20260726/system_health_check.py
- execute_plan
- ingest_report
- assess_idea.py
- decision_register.py
- document_qa.py
- evaluator.py
- homelab_discoverer.py
- .add_context
- self_correction.py
- task_executor.py
- alerts_delivery.py
- autonomous_fixer_v2.py
- Handler
- .write
- select_reasoning
- check_mcp_health
- artifact_manager.py
- deduplicate_jsonl
- learning_integrator.py
- pre-n8n-reduce-20260725/morning_briefing.py
- check_command
- process_supervisor.py
- bridge_workflows.cjs
- check_command
- homelab_reporter.py
- logrotate_wrapper.sh script
- duckdns_puppeteer.py
- clean_task_queue.py
- _collect_containers
- flock_wrapper.sh
- delegate
- crg_context.py
- hermes_autonomous_brain.py
- deploy_flow
- dns_healthcheck.sh
- gdrive_keepalive.sh
- init_collaborator_memory.sh
- morning_briefing.py
- renew-local-certs.sh
- analyze_effectiveness
- memory_sync.sh
- disk_watch.sh
- resource_monitor.sh
- unhealthy_restart.sh
- send_telegram
- crg_register_repo.sh
- debloat.sh
- docker_ghost_check.sh
- duckdns_update.sh
- gateway-preflight.sh
- package_status_cron.sh
- systemd_sanity_check.sh

## God Nodes (most connected - your core abstractions)
1. `handler()` - 32 edges
2. `send_telegram()` - 26 edges
3. `handler()` - 25 edges
4. `UnifiedMemory` - 24 edges
5. `run_cycle()` - 20 edges
6. `HermesMemory` - 19 edges
7. `record()` - 18 edges
8. `LoopState` - 18 edges
9. `SkillRegistry` - 17 edges
10. `GraphRAG` - 16 edges

## Surprising Connections (you probably didn't know these)
- `cmd_homelab_pipeline()` --calls--> `push_to_telegram()`  [INFERRED]
  hermes_mcp_server.py → .archive/pre-n8n-reduce-20260725/homelab_reporter.py
- `send_telegram()` --calls--> `_send()`  [INFERRED]
  .archive/unused-20260726/career_autonomous.py → syslog_emit.py
- `send_telegram()` --calls--> `_send()`  [INFERRED]
  career_engine.py → syslog_emit.py
- `_call_tool()` --calls--> `handler()`  [INFERRED]
  hermes_mcp_server.py → n8n_bridge_server.py
- `escalate_to_human()` --calls--> `send_to_telegram()`  [INFERRED]
  human_escalation.py → mind_loop.py

## Import Cycles
- None detected.

## Communities (145 total, 27 thin omitted)

### Community 0 - "gateway_guardian.py"
Cohesion: 0.07
Nodes (32): gateway_active(), main(), module_importable(), pre_snapshot_commit(), Return SHAs of recent auto-fix-snapshot commits., Get the commit just before the snapshot (the known-good state)., Hard reset to a known-good commit. DESTROYS working directory state., Reinstall hermes-agent from PyPI as last resort. (+24 more)

### Community 1 - "unused-20260726/hermes_mcp_server.py"
Cohesion: 0.08
Nodes (37): cmd_approve(), cmd_decisions(), cmd_digest(), cmd_homelab_discover(), cmd_homelab_optimize(), cmd_homelab_pipeline(), cmd_homelab_report(), cmd_homelab_status() (+29 more)

### Community 2 - "UnifiedMemory"
Cohesion: 0.09
Nodes (21): Fact, main(), MemoryResult, Connection, Path, Store a value in the unified memory store., Get a value from the unified memory store., Search memory using FTS5 text search + optional Qdrant vector search. (+13 more)

### Community 3 - "proactive_engine.py"
Cohesion: 0.08
Nodes (41): _candidate_actions(), _capsule_fail_rate(), _content_hash(), escalate_to_human(), execute_plan(), get_predictions(), get_thresholds(), _health_score() (+33 more)

### Community 4 - "handler"
Cohesion: 0.10
Nodes (32): _cg_arch(), _cg_dead(), _cg_impact(), _cg_query(), _cg_search(), _cg_status(), _crg(), handle_all_services_status() (+24 more)

### Community 5 - "research_engine.py"
Cohesion: 0.14
Nodes (34): approve_item(), cmd_approve(), cmd_clear_sent(), cmd_discover(), cmd_recommend(), cmd_status(), discover_all(), discover_github_trending() (+26 more)

### Community 6 - "handler"
Cohesion: 0.10
Nodes (26): _call_tool(), call_tool, handle_all_services_status(), handle_backup_status(), handle_cert_check(), handle_disk_usage(), handle_docker_exec(), handle_docker_images() (+18 more)

### Community 7 - "commitment_tracker.py"
Cohesion: 0.13
Nodes (28): Test the full commitment lifecycle., test_commitment_lifecycle(), check_commitments(), load_commitments_from_data(), push_alert(), Load from data/commitments.json (new system) or commitments.json (old system)., main(), Scan a message for commitments and auto-register them. Returns: {… (+20 more)

### Community 8 - "hermes_mcp_server.py"
Cohesion: 0.11
Nodes (27): _call_tool(), cmd_approve(), cmd_decisions(), cmd_digest(), cmd_homelab_discover(), cmd_homelab_optimize(), cmd_homelab_pipeline(), cmd_homelab_report() (+19 more)

### Community 9 - "package_tracker.py"
Cohesion: 0.12
Nodes (29): _detect_order_refs(), _detect_status_from_text(), _extract_estimated_delivery(), _extract_tracking_numbers(), _fetch_carrier_status(), get_alerts(), _get_body_from_payload(), _get_gmail_service() (+21 more)

### Community 10 - "pre-n8n-reduce-20260725/homelab_reporter.py"
Cohesion: 0.10
Nodes (21): count_recent_logs(), format_for_telegram(), generate_daily_digest(), generate_short_report(), get_container_summary(), get_resource_summary(), push_to_telegram(), homelab_reporter.py — Generates Telegram digest reports Weekly health summary,… (+13 more)

### Community 11 - "calendar_intelligence.py"
Cohesion: 0.12
Nodes (26): cache_events(), check_upcoming_reminders(), fetch_events(), format_event(), generate_briefing_section(), get_calendar_service(), get_event_prep(), get_next_event() (+18 more)

### Community 12 - "career_engine.py"
Cohesion: 0.13
Nodes (27): evaluate_job(), follow_up_stale(), generate_materials(), get_pipeline_status(), job_search(), load_seen_urls(), load_state(), log() (+19 more)

### Community 13 - "career_autonomous.py"
Cohesion: 0.14
Nodes (26): evaluate_job(), filter_new_matches(), follow_up_stale(), generate_materials(), get_pipeline_status(), job_search(), load_research_state(), load_state() (+18 more)

### Community 14 - "insight_engine.py"
Cohesion: 0.14
Nodes (25): generate_insights(), get_calendar_signals(), get_capsule_signals(), get_conversation_signals(), get_email_signals(), get_external_signals(), get_goal_signals(), get_health_signals() (+17 more)

### Community 15 - "HermesMemory"
Cohesion: 0.17
Nodes (7): HermesMemory, main(), MemoryResult, Connection, Path, Store a fact in the temporal KG., Get timeline of facts about an entity.

### Community 16 - "hermes_mind.py"
Cohesion: 0.18
Nodes (23): auto_retire(), check_predictive(), check_telegram_approvals(), config_fix_with_backup(), container_healthy(), get_container_logs(), _get_memory(), git_rollback_if_needed() (+15 more)

### Community 17 - "GraphRAG"
Cohesion: 0.18
Nodes (10): GraphContext, GraphRAG, main(), Connection, Path, Build entity network around a given entity., Standalone entity extraction entry point. Runs via cron., Full GraphRAG query: extract entities, traverse graph, return context. (+2 more)

### Community 18 - "ace_playbook.py"
Cohesion: 0.19
Nodes (20): approve_candidate(), auto_review(), _auto_score(), _draft_update(), generate_candidate(), get_stats(), _has_capsule_support(), load_pending() (+12 more)

### Community 19 - "LoopState"
Cohesion: 0.13
Nodes (10): LoopState, Return the merged context packet for an id (probe tails, prior reflections).…, Record the outcome of the most recent action. Drives the stagnation counter on…, True if the id is waiting on a human (stagnation gate tripped)., Mark an item as pruned (resolved)., Move item to Human Inbox., Move stale items to Pruned/Noise. Never deletes. Items in High Priority or…, Render state as human-readable markdown. (+2 more)

### Community 20 - "predictive_signals.py"
Cohesion: 0.15
Nodes (19): analyze_all_signals(), collect_current_signals(), compute_trend(), _ensure_history_dir(), get_predictions(), get_signal_history(), main(), predict_time_to_threshold() (+11 more)

### Community 21 - "pre-n8n-reduce-20260725/homelab_troubleshooter.py"
Cohesion: 0.18
Nodes (19): check_common_issues(), check_container(), cmd_exclude_add(), cmd_exclude_list(), cmd_exclude_remove(), diagnose_container(), fix_container(), get_all_containers() (+11 more)

### Community 22 - "bmoe_server.py"
Cohesion: 0.16
Nodes (10): BmoeSession, chat_completions(), _format_prompt(), health(), list_models(), get, Request, shutdown() (+2 more)

### Community 23 - "curious_explorer.py"
Cohesion: 0.16
Nodes (19): find_adjacent_topics(), find_contrarian_takes(), find_cross_pollination(), get_arxiv_papers(), get_github_trending(), load_interest_profile(), load_seen(), _log_to_journal() (+11 more)

### Community 24 - "SkillRegistry"
Cohesion: 0.19
Nodes (4): create_homelab_skills(), Register existing homelab scripts as formal skills, seed_global_skills(), SkillRegistry

### Community 25 - "send_telegram"
Cohesion: 0.16
Nodes (17): extract_body(), main(), port_check(), _post(), Send Markdown-formatted message., Send message with no parsing (plain text)., Send message to a specific forum topic by name. Args: topic: One of "general",…, Backwards-compatible function matching hermes CLI signature. Usage:… (+9 more)

### Community 26 - "Scheduler"
Cohesion: 0.22
Nodes (6): define_jobs(), Job, main(), datetime, Schedule, Scheduler

### Community 27 - "mind_loop.py"
Cohesion: 0.15
Nodes (18): load_state(), observe_calendar(), observe_email(), observe_external_signals(), observe_health(), observe_telegram_history(), Quick health snapshot., Check for new emails. (+10 more)

### Community 28 - "soul_overlay_gen.py"
Cohesion: 0.15
Nodes (17): generate_career(), generate_infra(), generate_knowledge(), generate_media(), generate_personal(), generate_research(), generate_travel(), main() (+9 more)

### Community 29 - "hc_uuids.sh"
Cohesion: 0.12
Nodes (15): log(), cve_monitor.sh script, hc_ping.sh script, HC_UUID_AUTONOMOUS_FIXER, HC_UUID_BACKUP_VOLUMES, HC_UUID_CONSOLIDATED_HEALTH, HC_UUID_CVE_SCAN, HC_UUID_DB_BACKUP (+7 more)

### Community 30 - "GNAPAgent"
Cohesion: 0.23
Nodes (5): AgentManifest, Capability, GNAPAgent, main(), Path

### Community 31 - "Guardrails"
Cohesion: 0.21
Nodes (5): Guardrails, GuardResult, Policy, Any, Path

### Community 32 - "temporal_kg.py"
Cohesion: 0.22
Nodes (17): add_decision(), ensure_decisions_table(), get_db(), get_stats(), get_timeline(), ingest_capsules(), ingest_health_dashboards(), main() (+9 more)

### Community 33 - "pre-n8n-reduce-20260725/system_doctor.py"
Cohesion: 0.26
Nodes (15): check_crawl4ai_mcp(), check_disk(), check_processes(), clean_docker(), clean_orphaned_locks(), doctor(), handle_telegram_409(), load_state() (+7 more)

### Community 34 - "decision_ledger.py"
Cohesion: 0.20
Nodes (12): _fmt(), load(), main(), _now(), Close an open entry with the actual outcome + evidence., resolve(), stats(), execute_plan() (+4 more)

### Community 35 - "run_cycle"
Cohesion: 0.16
Nodes (17): anticipate(), append_insight(), create_plan(), evolve(), find_patterns(), log(), Append an insight to the persistent insight log., Find cross-domain patterns and novel insights. (+9 more)

### Community 36 - "personal_research_digest.py"
Cohesion: 0.18
Nodes (16): format_digest(), gather_local_context(), generate_deep_research(), generate_digest(), load_config(), load_history(), Run GPT-Researcher on a query via the container. Modes: standard —…, Gather relevant local documents to enrich research context. Searches Paperless-… (+8 more)

### Community 37 - "QualityTracker"
Cohesion: 0.24
Nodes (5): Interaction, datetime, Path, QualityReport, QualityTracker

### Community 38 - "hermes_health.py"
Cohesion: 0.23
Nodes (15): _backup_freshness(), _count_status(), _disk_usage(), _docker_ps(), format_compact(), format_health(), _last_scan_freshness(), _llm_reachable() (+7 more)

### Community 39 - "research_consumer.py"
Cohesion: 0.18
Nodes (15): classify_finding(), consume(), load_recent_findings(), main(), parse_digest(), Append a classified finding to the research log., Load findings from the last N hours (default: 7 days)., Route an actionable finding to the BabyAGI task queue. (+7 more)

### Community 40 - "skill_library.py"
Cohesion: 0.25
Nodes (15): add_skill(), _count_by_key(), extract_from_capsule(), get_stats(), load_index(), main(), Record a skill usage outcome., Scan capsule outcomes for successful novel approaches worth extracting. (+7 more)

### Community 41 - "record"
Cohesion: 0.22
Nodes (15): Open a ledger entry. Returns the entry (with id) for later resolve()., record(), _check_budget(), escalate_to_human(), get_escalation_stats(), handle_human_response(), _load_budget(), main() (+7 more)

### Community 42 - "persona_engine.py"
Cohesion: 0.20
Nodes (14): compress_context(), generate_alert_prefix(), generate_checkin(), generate_evening_reflection(), get_calendar_context(), get_interest_profile(), get_system_state(), pick_random() (+6 more)

### Community 43 - "unused-20260726/unified_cost_guard.py"
Cohesion: 0.25
Nodes (14): check(), check_billing(), check_claude_code(), check_hermes_proxy(), get_openrouter_key(), load_json(), log(), Verify Hermes proxy config uses free providers. (+6 more)

### Community 44 - "capsule_tracker.py"
Cohesion: 0.25
Nodes (13): check_target_health(), ensure_dir(), get_stats(), load_capsules(), main(), Best-effort re-check of a target's health. Returns 'success'|'fail'|None., Re-check target health and append verification to the latest matching record., Record a Capsule outcome. (+5 more)

### Community 45 - "experiment_engine.py"
Cohesion: 0.23
Nodes (13): execute_experiment(), get_experiment_stats(), _load_experiments(), main(), _maybe_promote_winner(), Record experiment outcome (success/fail/partial)., Check if a variant has enough evidence to be promoted as default., Run an experiment for the given action. (+5 more)

### Community 46 - "feedback_loop.py"
Cohesion: 0.20
Nodes (14): check_action_outcomes(), generate_adjustments(), generate_report(), load_data(), load_feedback(), log_suggestion(), Analyze patterns and recommend adjustments to proactive behavior., Record an action in the decision ledger (proactive suggestion or command). (+6 more)

### Community 47 - "send_to_telegram"
Cohesion: 0.24
Nodes (14): Send a message to Telegram via bridge, with deduplication., send_to_telegram(), is_duplicate(), _is_trending_message(), load_cache(), _normalize(), Register that a message was sent., Normalize text for comparison — lowercase, strip whitespace, remove emoji… (+6 more)

### Community 48 - "unified_cost_guard.py"
Cohesion: 0.25
Nodes (14): check(), check_billing(), check_claude_code(), check_hermes_proxy(), get_openrouter_key(), load_json(), log(), Verify Hermes proxy config uses free providers. (+6 more)

### Community 49 - "process_conversations"
Cohesion: 0.22
Nodes (13): extract_with_llm(), get_recent_sessions(), get_session_messages(), main(), process_conversations(), Use LLM to extract memories, action items, and strategy outcomes., Save a memory to claudemem.db., Save a strategy outcome to the Capsule log. (+5 more)

### Community 50 - "Span"
Cohesion: 0.20
Nodes (5): _generate_id(), Any, Aggregate trace stats for quality tracking., Span, Tracer

### Community 51 - "homelab_optimizer.py"
Cohesion: 0.23
Nodes (13): get_docker_stats(), get_system_metrics(), optimize(), optimize_alert_thresholds(), optimize_log_retention(), optimize_resource_limits(), homelab_optimizer.py — Self-optimization engine Tunes resource limits,…, Optimize Docker log retention based on disk usage (+5 more)

### Community 52 - "install_manager.py"
Cohesion: 0.27
Nodes (12): do_install(), format_review(), _log(), main(), _months_since(), Actually perform the installation., Review a GitHub repo for safety and relevance., Check if an apt package exists and get info. (+4 more)

### Community 53 - "unused-20260726/unified_memory_mcp.py"
Cohesion: 0.33
Nodes (12): call_tool(), exec_sql(), handle_query(), handle_recall(), handle_stats(), handle_store(), list_tools(), call_tool (+4 more)

### Community 54 - "proactive_orchestrator.py"
Cohesion: 0.26
Nodes (12): format_briefing(), _hash_message(), orchestrate(), push_to_alerts_inbox(), Check if a similar message was delivered in the last 12 hours., Push a message to the alerts inbox for Telegram delivery., Run a Python script and return (success, output)., read_curious_explorer_results() (+4 more)

### Community 55 - "unified_memory_mcp.py"
Cohesion: 0.33
Nodes (12): call_tool(), exec_sql(), handle_query(), handle_recall(), handle_stats(), handle_store(), list_tools(), call_tool (+4 more)

### Community 56 - "autonomous_fixer.py"
Cohesion: 0.36
Nodes (10): check_capsule_trends(), check_disk_pressure(), check_docker_health(), check_gateway_stability(), load_state(), log(), main(), _probe_for() (+2 more)

### Community 57 - "email_intelligence.py"
Cohesion: 0.24
Nodes (11): categorize_email(), fetch_recent_emails(), format_digest(), get_gmail_service(), push_to_inbox(), Compose a categorized email digest., Push digest to alerts_inbox for Telegram delivery., Build and return a Gmail API service with valid credentials. Retries transient… (+3 more)

### Community 58 - "homelab_troubleshooter.py"
Cohesion: 0.35
Nodes (11): check_container(), cmd_exclude_add(), cmd_exclude_list(), cmd_exclude_remove(), diagnose_container(), diagnose_cycle(), get_all_containers(), load_excluded() (+3 more)

### Community 59 - "adaptive_thresholds.py"
Cohesion: 0.31
Nodes (10): adapt_thresholds(), analyze_outcomes(), get_thresholds(), ledger_load(), _load_thresholds(), main(), Adapt thresholds based on historical outcomes., Get current adaptive thresholds (for use by proactive_engine). (+2 more)

### Community 60 - "autonomous_work_session.py"
Cohesion: 0.38
Nodes (10): commitment_check(), health_snapshot(), log(), main(), Quick health snapshot., Check for overdue commitments., Review pending tasks., run_cmd() (+2 more)

### Community 61 - "homelab_deployer.py"
Cohesion: 0.31
Nodes (10): backup_compose(), deploy(), deploy_mcp_server(), log_deploy(), homelab_deployer.py — Auto-deploys evaluated candidates Handles: MCP server…, Add MCP server to opencode config, Run basic health check after deployment, run_cmd() (+2 more)

### Community 62 - "homelab_evaluator.py"
Cohesion: 0.27
Nodes (10): evaluate(), evaluate_candidate(), get_current_stack(), get_resource_usage(), load_state(), homelab_evaluator.py — Evaluates discovered candidates for deployment Reads…, Return list of Docker images currently running, Return current resource usage summary (+2 more)

### Community 63 - "system_doctor.py"
Cohesion: 0.42
Nodes (9): check_processes(), clean_orphaned_locks(), doctor(), handle_telegram_409(), load_state(), log(), save_state(), send_alert() (+1 more)

### Community 64 - "trip_planner.py"
Cohesion: 0.45
Nodes (10): cmd_countdown(), cmd_itinerary(), cmd_status(), cmd_task_add(), cmd_tasks(), cmd_today(), _load_tasks(), _load_trip() (+2 more)

### Community 65 - "backup_health.py"
Cohesion: 0.40
Nodes (8): check_backups(), check_git_repos(), check_kopia(), check_rclone(), get_last_backup(), main(), run(), send_telegram()

### Community 66 - "pre-n8n-reduce-20260725/system_health_check.py"
Cohesion: 0.38
Nodes (9): check_docker(), check_port(), check_process(), check_systemd(), check_telegram_gateway(), load_state(), main(), save_state() (+1 more)

### Community 67 - "self_prune.py"
Cohesion: 0.33
Nodes (8): archive_dead_script(), disable_job_in_scheduler(), log_action(), prune(), Move a dead script to state/archive/dead/., Set enabled=False for a job in the scheduler script., read_report(), send()

### Community 68 - "system_health_check.py"
Cohesion: 0.38
Nodes (9): check_docker(), check_port(), check_process(), check_systemd(), check_telegram_gateway(), load_state(), main(), save_state() (+1 more)

### Community 69 - "sync_with_autonomous_fixer"
Cohesion: 0.33
Nodes (8): analyze_capsule_patterns(), generate_lazy_dev(), load_playbook(), Return genes with failure counts > 3., Create lazy-dev playbook entry for problematic gene., Generate and store lazy-dev entries for failing genes., save_playbook(), sync_with_autonomous_fixer()

### Community 70 - "n8n_mcp.py"
Cohesion: 0.25
Nodes (7): call_tool(), list_tools(), call_tool, list_tools, TextContent, Tool, _trigger_webhook()

### Community 71 - "pii_classifier.py"
Cohesion: 0.28
Nodes (8): classify(), main(), Quick check: should this text be routed to local LLM only?, Redact PII from text — replace with placeholders., CLI interface for testing., Classify text for PII content. Returns: { "has_pii": bool, "risk": "high" |…, redact_pii(), should_route_to_local()

### Community 72 - "review_traces.py"
Cohesion: 0.33
Nodes (8): auto_label(), export_labeled(), interactive_review(), load_entries(), load_labeled(), Auto-label entries using heuristic rules., Walk through unlabeled entries and let user assign labels., show_stats()

### Community 73 - "backup_all.py"
Cohesion: 0.53
Nodes (8): db_dumps(), kopia_dirs(), kopia_volumes(), main(), run(), running_containers(), step(), sudo_test()

### Community 74 - "capability_tracker.py"
Cohesion: 0.33
Nodes (8): append_history(), build_report(), Parse scheduler script to extract job metadata (description, tags, enabled)., Append a time-stamped snapshot of all job states to the history log., Analyze history and build a capability report., read_job_definitions(), read_scheduler_state(), track()

### Community 75 - "changelog_gen.py"
Cohesion: 0.39
Nodes (8): build_changelog(), extract_narrative(), format_capsules(), git_log(), main(), parse_capsules(), Extract hand-written narrative section between markers., run()

### Community 76 - "claude_md_sync.py"
Cohesion: 0.39
Nodes (8): gen_containers(), gen_cron_jobs(), gen_storage_live(), gen_system_stats(), gen_systemd_live(), _replace_named(), run(), sync()

### Community 77 - "config_snapshot.py"
Cohesion: 0.39
Nodes (7): capture(), diff(), _get_crontab(), _get_disk(), _get_docker_ps(), _get_model_config(), save()

### Community 78 - "daily_research.py"
Cohesion: 0.31
Nodes (8): assess_impact(), atomic_json_write(), main(), Path, Assess the potential impact of a repository, Run GitHub API search, Write JSON atomically: dump to temp file in same dir, then rename. Prevents…, run_search()

### Community 79 - "local_anthropic_proxy.py"
Cohesion: 0.33
Nodes (8): head, api_hello(), health(), log(), messages(), models(), get, Request

### Community 80 - "RunLog"
Cohesion: 0.22
Nodes (5): Path, Append-only JSONL run log for observability., Query recent entries., Return last N entries., RunLog

### Community 81 - "interest_model.py"
Cohesion: 0.50
Nodes (8): build_profile(), extract_topics(), load_json(), load_jsonl_lines(), score_from_personal_model(), score_from_research(), score_from_sessions(), score_from_telegram()

### Community 82 - "pre-n8n-reduce-20260725/task_executor.py"
Cohesion: 0.54
Nodes (7): execute_infra_task(), execute_research_task(), execute_task(), load_queue(), push_alert(), run(), save_queue()

### Community 83 - "homelab_orchestrator.py"
Cohesion: 0.29
Nodes (7): push_alert(), homelab_orchestrator.py — Master orchestrator for homelab autonomous pipeline…, Push a Telegram alert, Run a homelab script and return output, Run the entire autonomous pipeline in sequence, run_full_pipeline(), run_script()

### Community 84 - "unused-20260726/system_health_check.py"
Cohesion: 0.46
Nodes (7): check_port(), check_process(), check_telegram_gateway(), load_state(), main(), save_state(), telegram_alert()

### Community 85 - "execute_plan"
Cohesion: 0.25
Nodes (8): compose_morning_briefing(), execute_plan(), Execute the planned actions with guardrails and quality tracking., Record an action in the feedback loop for outcome tracking., Compose a morning briefing message., Add a task to the persistent task queue., _record_feedback(), task_queue_add()

### Community 86 - "ingest_report"
Cohesion: 0.39
Nodes (7): extract_entities(), ingest_report(), main(), Path, Extract key entities from research text for KG ingestion., Ingest a single report into temporal_kg., run()

### Community 87 - "assess_idea.py"
Cohesion: 0.52
Nodes (6): assess(), call_ollama(), call_proxy(), fetch_url(), fmt(), main()

### Community 88 - "decision_register.py"
Cohesion: 0.52
Nodes (6): add(), dashboard(), get_conn(), intake(), list_items(), score()

### Community 89 - "document_qa.py"
Cohesion: 0.52
Nodes (6): format_document_results(), get_recent_documents(), _load_credentials(), main(), search_immich(), search_paperless()

### Community 90 - "evaluator.py"
Cohesion: 0.48
Nodes (6): auto_evaluate_digest(), auto_evaluate_troubleshoot(), evaluate(), init(), Auto-score the last daily digest, trend()

### Community 91 - "homelab_discoverer.py"
Cohesion: 0.48
Nodes (6): discover(), fetch_json(), load_state(), homelab_discoverer.py — Autonomous discovery engine Scans GitHub trending,…, save_state(), score_repo()

### Community 92 - ".add_context"
Cohesion: 0.29
Nodes (4): _merge_context(), Upsert by item['id']. Returns the item after update. Gates applied here (single…, Append a probe/reflection entry into the id's context ring. No-op if the id has…, Ring-buffer context packet. Keys are epochs; we keep newest CTX_MAX_ENTRIES.

### Community 93 - "self_correction.py"
Cohesion: 0.43
Nodes (6): check_scheduler_health(), check_task_results(), push_alert(), Check recently completed tasks — did they actually resolve the issue?, Check if most scheduler jobs are succeeding., run()

### Community 94 - "task_executor.py"
Cohesion: 0.57
Nodes (6): execute_research_task(), execute_task(), load_queue(), push_alert(), run(), save_queue()

### Community 95 - "alerts_delivery.py"
Cohesion: 0.47
Nodes (4): _dedup(), deliver(), Remove duplicate alert messages by source+msg hash., send_message()

### Community 96 - "autonomous_fixer_v2.py"
Cohesion: 0.40
Nodes (5): check_all(), log(), Execute via DesktopCommanderMCP if available., Run all checks with fallback., run_with_desktop_commander()

### Community 98 - ".write"
Cohesion: 0.33
Nodes (5): main_stdio(), main(), main_stdio(), Write rendered markdown to STATE_FILE., main()

### Community 99 - "select_reasoning"
Cohesion: 0.47
Nodes (5): classify_task(), main(), Select the best reasoning structure for a task., Simple keyword-based task type classifier., select_reasoning()

### Community 100 - "check_mcp_health"
Cohesion: 0.53
Nodes (5): check_mcp_health(), main(), Check if MCP server is responsive., Restart MCP server with backoff., restart_with_backoff()

### Community 101 - "artifact_manager.py"
Cohesion: 0.47
Nodes (5): format_artifact_report(), init(), list_artifacts(), Generate a daily markdown report from pipeline state, save_artifact()

### Community 102 - "deduplicate_jsonl"
Cohesion: 0.33
Nodes (5): deduplicate_jsonl(), prune_capsules(), Path, Remove duplicate entries based on key combo. Return count removed., Keep only last N capsule entries.

### Community 103 - "learning_integrator.py"
Cohesion: 0.47
Nodes (5): analyze_session_patterns(), main(), Find common failure patterns in logs., Generate improvement suggestions for SOUL.md., suggest_improvements()

### Community 104 - "pre-n8n-reduce-20260725/morning_briefing.py"
Cohesion: 0.60
Nodes (3): briefing(), read_json(), send()

### Community 105 - "check_command"
Cohesion: 0.50
Nodes (4): check_command(), Check if command is destructive. Returns (is_safe, reason)., Run command with guard., run_guarded()

### Community 106 - "process_supervisor.py"
Cohesion: 0.40
Nodes (4): ensure_running(), ensure_single(), Restart if not running., Kill all except most recent instance.

### Community 107 - "bridge_workflows.cjs"
Cohesion: 0.40
Nodes (3): db, s, workflows

### Community 108 - "check_command"
Cohesion: 0.50
Nodes (4): check_command(), Check if command is destructive. Returns (is_safe, reason)., Run command with guard., run_guarded()

### Community 112 - "clean_task_queue.py"
Cohesion: 0.83
Nodes (3): clean(), _parse_ts(), datetime

### Community 113 - "_collect_containers"
Cohesion: 0.67
Nodes (3): _collect_containers(), main(), Collect container status from Docker.

## Knowledge Gaps
- **29 isolated node(s):** `disk_watch.sh script`, `resource_monitor.sh script`, `unhealthy_restart.sh script`, `memory_sync.sh script`, `s` (+24 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **27 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `send_telegram()` connect `send_telegram` to `personal_research_digest.py`, `send_telegram`, `research_engine.py`, `persona_engine.py`, `calendar_intelligence.py`, `career_engine.py`, `career_autonomous.py`, `send_to_telegram`, `mind_loop.py`, `alerts_delivery.py`?**
  _High betweenness centrality (0.083) - this node is a cross-community bridge._
- **Why does `record()` connect `record` to `decision_ledger.py`, `proactive_engine.py`, `experiment_engine.py`, `feedback_loop.py`, `hermes_mind.py`, `execute_plan`, `mind_loop.py`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Why does `_send()` connect `gateway_guardian.py` to `research_engine.py`, `personal_research_digest.py`, `career_autonomous.py`, `send_telegram`?**
  _High betweenness centrality (0.016) - this node is a cross-community bridge._
- **What connects `disk_watch.sh script`, `resource_monitor.sh script`, `unhealthy_restart.sh script` to the rest of the system?**
  _29 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `gateway_guardian.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06775510204081632 - nodes in this community are weakly interconnected._
- **Should `unused-20260726/hermes_mcp_server.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07575757575757576 - nodes in this community are weakly interconnected._
- **Should `UnifiedMemory` be split into smaller, more focused modules?**
  _Cohesion score 0.09408033826638477 - nodes in this community are weakly interconnected._