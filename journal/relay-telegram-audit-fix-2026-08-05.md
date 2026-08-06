# Relay — Telegram Notification Audit & Fix (2026-08-05)

## Task
Comprehensive audit of every Telegram notification received by Relay, then fix all issues.

## What was found
- **14 senders, 2 paths**: 7 through the `:9199` n8n bridge, 7 exploiting the direct bot API
  (`api.telegram.org/bot.../sendMessage`) bypassing any central dedup.
- **Feedback loop (worst issue)**: the `telegram-notify` hook posts `✅ Agent turn done` to the
  channel, but the agent monitors that same Telegram channel and **replies to its own
  notifications** — confirmed 2+ such self-replies in `agent.log.1`. Every `agent:end` turn
  (>80 chars) posted a duplicate notification.
- Scheduler jobs run scripts via subprocess (not agent turns) and each sends independently.
- `system_health_check` / `gateway_guardian` already only alert on new failures (clean).
- `system_doctor` dedup was fixed earlier (commit `6112114`).

## Fixes applied (commit `5cd9c39`)
1. **Central dedup** — `n8n_bridge_server.py` `/telegram-send`: exact-match dedup keyed on
   `chat_id|text` with a 120s window; state in `~/.hermes/data/telegram_dedup.json`. Verified
   live: identical send is suppressed, distinct sends pass.
2. **Feedback-loop guard** — `telegram-notify/handler.py`: skip `agent:end` when the triggering
   message contains our own markers (`✅ Agent turn done`, `⚙️ Bridge /`); raised response
   threshold 80 → 400 chars.
3. **Consolidate direct senders to central bridge** (6 files cleaned): `alerts_delivery`,
   `calendar_intelligence`, `persona_engine`, `system_doctor`, `self_prune`,
   `system_health_check` — all now route through `telegram_bridge.send_telegram → /telegram-send`
   (deduped). Removed dead `BOT_TOKEN`/`SEND_URL`/direct-API code.

## Verification
- Bridge dedup live-tested: `{"deduped": true}` on 2nd identical send; distinct send OK.
- All 6 consolidated scripts: `ast.parse` OK, no remaining `api.telegram.org/bot` direct send.
- `telegram_bridge` import resolves on homelab.
- Services restarted: `hermes-gateway`, `hermes-mind-loop`; hooks reloaded (visible in
  journal: `[hooks] Loaded hook 'telegram-notify'`).
- **Remaining findings left intact**: `gateway_guardian.py` uses `TELEGRAM_API` only as a
  reachability probe (no send) — unchanged.

## Anti-fabrication enforcement

A new hook `verify-agent-claims` (events: `agent:step` + `agent:end`) was added:
- Accumulates executed tool names per `session_id` from `agent:step` events.
- At `agent:end`, if the response claims action (backtick command or state-change verb) but zero tools executed in the turn → logs to `state/verify_agent_claims.jsonl` and posts a `⚠️ Not verified` follow-up to the Telegram channel.
- Non-blocking, never rewrites the agent reply.
- Catches the exact pattern that produced the `claude_md_sync.py` false claim (api_calls=1, no tool evidence).


## Comprehensive scan (2026-08-06)

### Issues found and fixed:
1. **collaborator-memory graph stale** — `code-review-graph` was registered for the collaborator-memory repo (a markdown knowledge base), but CRG only indexes code files. Graph had 0 nodes. Fixed by unregistering the repo from CRG (`code-review-graph unregister collaborator-memory`).
2. **hermes-upgrade.service failed** — `hermes_upgrade.py` had a SyntaxError at line 54 from a previous broken version. Script is now syntactically valid; service was reset with `systemctl --user reset-failed`.
3. **mind-loop crash** — `tracer` was `None` (hermes_tracing not installed) but `tracer.span()` was called unconditionally every 30 min, causing `NoneType object has no attribute span`. Fixed by adding a `_NullTracer`/`_NullSpan` fallback when tracing is unavailable.
4. **Stale locks** — `auth.lock` (0 bytes, Jul 23) removed; `kanban.db.init.lock` and `.tick.lock` cleaned by system_doctor.
5. **Uncompressed rotated logs** — `errors.log.2` (2.0M) and `monitoring_bundle.log.1` (1.2M) compressed with gzip.
6. **Disk** — 55% used (115G/221G), healthy.
7. **Docker** — 35 containers, all running normally.
8. **MCP servers** — `desktop_commander` and `code-review-graph` MCP servers retry at startup (pre-existing, not persistent errors).

## Notes for next run
- Watch channel for a day; if quiet-channel desired on `system_health_check`, add
  `disable_notification` support through the bridge if needed (currently not passed).
- New senders should always use `telegram_bridge.send_telegram` (never direct bot API).