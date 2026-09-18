# Regression egress fix + full agent LLM-governance audit (Sep 18 2026)

## Task
1. "fix it now" — the regression `tg-send` check only proved throttle-acceptance,
   not real Telegram delivery (Round-9: the bridge poller never loaded a token, so
   egress was dead for days while `tg-send: PASS`).
2. "confirm how my agents are set up" — verify every agent is non-deterministic /
   LLM-determined, guarded only against disasters, and has autonomy, leverage,
   identity, and continuous learning/evolution.

## 1. Real egress in regression (9/9 suite)
- **New `tg-egress` check**: direct `sendMessage` to api.telegram.org with the same
  token the bridge loads (`TELEGRAM_BOT_TOKEN` from `~/.hermes/.env`, mirrored via
  `_env_file()` exactly like the bridge resolves it). Requires `ok:true` +
  `message_id` (Bot API accepted delivery), then `deleteMessage` to self-clean.
  Any token/network/auth failure now FAILS the pre-commit gate loudly.
- **`tg-send` relabeled**: "bridge accepted (throttled=…)" — reachability/auth only.
- **Target**: home channel (`-1003976074764`) General topic, no thread.
  `TELEGRAM_HOME_CHANNEL_THREAD_ID=7338` is a DELETED topic ("message thread not
  found") — nothing consumes it (bridge defaults chat-only), kept in .env as dead
  config.
- **New `homelab-backups` check**: `homelab_agent.check_backups()` in a fresh
  subprocess (real `sudo -n kopia`, `_parse_json_stream` array-parse) — asserts
  `healthy` + ≥1 snapshot. Closes the Round-10 "future regression change" note.
- Verified: **9/9 PASS**, probe message invisible (delivered then deleted).

## 2. Agent governance audit — all LLM-determined
Matrix (see AGENTS.md Round-11 for the full table):
- **Roster ×8** (`agents/agent_loop.py`): `decide_action()` = hop haiku-4.5,
  grounded in personality + playbook + store; validated vs `known_subcommands()`
  (real dispatch surface); offline/malformed → deterministic `check`. Evolution
  written into `agentbus/memory/<name>.md` `## Evolution Log` every 20 cycles.
- **homelab** (`homelab_agent_autonomous.py`): LLM `plan()`, minimal rails
  (allowlist, signal-grounded targets, cooldowns, update gating, notify dedup).
- **jenny** (`jenny_chief.py` + `jenny_llm.py`): reactive LLM intent →
  `validate_intent` (tools allowlist, roster-only delegation, spawn/retire sanity,
  shell-danger regex on run_command).
- **orchestrator**: decompose → dispatch, CRG blast-radius high → proposal
  (human confirm), confidence gating.
- **mind_loop**: OBSERVE/CONNECT are deterministic context; PLANNING was the last
  deterministic decision point (`create_plan` keyword/priority rules).

### Fix: `llm_plan_overlay()` — mind_loop planning is now LLM-governed
- Added to `mind_loop_integration.py` (+ `_hop_ask` helper, same shape as the other
  agents). LLM reviews the deterministic candidate plans and returns
  `{"keep": [...], "defer": [...], "propose": {add_task|send_telegram}}`.
- Bounds (minimal, disaster-only): keep/defer must be valid indices; at most ONE
  new candidate, only `add_task`/`send_telegram` (never commands); empty `keep`
  = defer-all (legit LLM judgment, marked `_deferred_by_llm`).
- **Deterministic fallback preserved**: offline/malformed reply → original plans
  untouched (proven by unit check with dead HOP_URL).
- **Guardrails NOT loosened**: ACT-phase gate stays fail-closed (read-only
  run_command allowlist, confidence gating, CRG blast-radius → proposal).
- Wired into `mind_loop.py` run_cycle PLAN phase.
- Live test: real hop kept 1/3 plans (only the high-value send_telegram), deferred
  the rest → genuinely model-decided.
- hermes-mind-loop restarted; active.

## Lessons / notes
- A bridge/regression "PASS" is only as strong as what the check actually asserts.
  Prefer one strong assertion (delivery accepted by the real endpoint) over many
  weak ones (throttle acceptance, HTTP reachability).
- All learning/identity infra is live and verified present: `narrative_memory`,
  `feedback_loop`, `autonomous_self`, `personal_model`, `insight_engine`,
  `unified_memory`, per-agent identity + `## Evolution Log`.
- Stale duplicate `scripts/agent_loop.py` (pre-`known_subcommands`) is dead — units
  exec `agents/agent_loop.py`. Cleanup candidate for a future round.