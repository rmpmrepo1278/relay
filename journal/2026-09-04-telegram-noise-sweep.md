# Date: 2026-09-04 — Telegram noise sweep (false alarms + broken modules)

## What was spamming Telegram and why
1. **[commitment_executor] ⏳ Overdue Commitments (every 5m)** — "[trial]", "restart container ollama [trial]",
   "restore backup notes_journal". Leftovers from the agent-parliament live/synthetic smoke tests. **Fixed** by
   cleaning `commitments.json active[]`, `commitment_queue.json`, `decision_votes.json`, ballots, and DB rows
   (outcomes source=test/live-test, decision_register source=decision_council). Verified: `commitment_executor`
   now prints "No active commitments". Ledgers live in `state/*.json` + `data/commitments.json` `active[]`.
2. **[system_doctor] "Restarted hermes_gateway after detecting it was down" (every 30m, FALSE)** — root cause:
   `system_doctor.check_processes()` pgrep'd `hermes_cli.main gateway run` on the HOST, but the gateway runs
   INSIDE the hermes container (`/opt/hermes/.venv/bin/hermes gateway run --replace`, s6-supervised). Host pgrep
   never matches → it claimed a restart and alerted every 30m **without ever restarting anything** (the old code
   only ACTUALLY restarted the scheduler; gateway/docker_daemon branches only faked it). The gateway was never
   down — container up 19h, service up 67k s.
   **Fixed**: rewritten `check_processes()` — real docker-based health (`docker inspect hermes .State.Running`;
   `docker exec hermes /command/s6-svstat /run/service/gateway-default`), real s6-bounce (s6-svc -r, service name
   discovered from `ls /run/service`), and `_dedup_alert()` so a genuinely-restarted service alerts at most once/hr.
   No more false gateway-restart claims.
   NOTE: the gateway s6 service is named **gateway-default** (not gateway) — `/run/service/gateway` is wrong.
3. **[email_intelligence] "No module named 'google'"** — python3 lacked google-auth/google-oauth/apiclient
   (PEP-668 blocked). **Fixed**: `/usr/bin/python3 -m pip install --break-system-packages
   google-auth google-auth-oauthlib google-api-python-client`. Verified live: **real Gmail digest now works**
   ("7 emails, 1 actionable"). Token exists at `~/.hermes/gmail/token.json`. Added a quiet-skip if no token
   exists (future-proof) + `_log_only()` so unconfigured runs don't push inbox alerts.
4. **[autonomous_fixer / auto_fix_delegate]  🤖 AUTO-FIX SESSION STARTED / FAILED spam** — every claude-code
   session dies in ~5s with `[claude-code:unrecognized_model] {"model":"stealth/ox-alpha","query_source":"sdk"}`
   because `~/.claude/settings.json` pins `"model": "stealth/ox-alpha"` which claude-code does not recognize.
   **Fixed** at `~/agentharness/scripts/auto_fix_delegate.py`: detect `unrecognized_model` → report ONCE, then
   silence Telegram for 12h (state `~/.claude/state/auto_fix_model.json`); silenced sessions exit quietly
   (log-only) without STARTED/FAILED messages. Silence pre-set now, so pending flaps will be quiet.
   OPEN: real fix = a recognized model for claude-code (or ANTHROPIC_MODEL env) — reviewed but NOT changed to
   avoid guessing a model/cost.
5. **Duplicate "Autonomous Work Session — Morning/Afternoon" + duplicate council msgs** — caused by the
   two-scheduler-daemon window (a watchdog had auto-relaunched a 2nd daemon → jobs ran twice). Resolved by
   restoring a single daemon (see journal 2026-09-04-hardening-live-smoke.md).
6. **"Gateway: inactive" in work-session snapshots** — inaccurate value from that check path; cosmetic, not
   fixed yet (gateway is genuinely up).

## Files changed (host, ~/.hermes and ~/agentharness — not git-tracked, deliberate)
- `scripts/system_doctor.py` — docker-based gateway health, real restarts, alert dedup.
- `scripts/email_intelligence.py` — token-present gate + `_log_only`; libs installed.
- `agentharness/scripts/auto_fix_delegate.py` — model-error silence (report once per 12h).
- Cleaned: commitments/queue/slate/ballot ledgers + DB rows (already done prior journal).

## Verified
- email_intelligence → real digest (7 emails, 1 actionable).
- system_doctor → logs "gateway-default: up (pid 170)" — zero alerts.
- commitment_executor → no active commitments.
- auto-fix → silence file set; next sessions exit silently; approach limits reports to ≤1/12h.
- Scheduler still single daemon (PID 1647544), all jobs cycling.

## Open / follow-ups
- Auto-fix model config (stealth/ox-alpha) — decide a recognized model or set ANTHROPIC_MODEL so delegations
  actually execute (currently silenced, not functional).
- Work-session "Gateway: inactive" labeling mismatch (cosmetic).
- Consider noise-reduction for council propose/tally messages once balloting is fully automated.## Follow-up: auto-fix model decision (same day)
- User asked to set the model for the auto-fixer. Investigation:
  - `stealth/ox-alpha` is Hermes' internal Zen-relay model (models.py:136 `"free"`, 1M ctx) — NOT an OpenRouter id; claude-code on the host can only reach it if proxied through the Hermes gateway (not wired).
  - OpenRouter account status: **zero credits** (402 "Insufficient credits" on paid models), usage=32.86 lifetime, NOT free tier. OpenRouter now **rate-limits ALL :free models for this account** (429 "free-models-per-day-high-balance" — even z-ai/glm-5.2:free and poolside/laguna-s-2.1:free which hermes pins as free). So no $0 host-side delegation path exists today.
- Set `~/.claude/settings.json`: `model = "anthropic/claude-haiku-4.5"`, `env.ANTHROPIC_MODEL` + `env.ANTHROPIC_SMALL_FAST_MODEL` = same (env bypasses claude-code's registry check; `CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT=1` already present). Backup at `settings.json.bak-1788566143`.
- Re-armed `~/.claude/state/auto_fix_model.json` (silenced_until +12h, reason funding-pending) so delegates stay Telegram-quiet until funded; delegate itself reports max once per 12h.
- Unblock: add a few credits at openrouter.ai/settings/credits → next auto-fix uses haiku-4.5 for real. Routing delegates through the Hermes Zen relay (proxy) is the free alternative; not implemented.## Follow-up: stealth/ox-alpha replaced with poolside/laguna-s-2.1:free
- User asked to replace the `stealth/ox-alpha` model (Hermes-internal Zen alias, unreachable from OpenRouter
  and unrecognized by claude-code) with a genuinely-free OpenRouter model like laguna, or remove it.
- Investigated every live reference inside the hermes container; `stealth/ox-alpha` was NOT an active model
  selection — only catalog/metadata entries. Laguna free variants (`poolside/laguna-s-2.1:free`,
  `poolside/laguna-xs-2.1:free`) were already in the free tier (models.py) and already covered in context
  metadata (262144 via substring match), so the system is now homogeneous on laguna.
- Edits applied in-container (backups +`.bak-stealth-replace` in-place):
  - `hermes_cli/models.py` (main + `.hermes/hermes-agent` mirror): free tier line
    `("stealth/ox-alpha", "free")` → `("poolside/laguna-s-2.1:free", "free")`, original duplicate laguna
    entry removed so it lists once at the top of the free tier.
  - `agent/model_metadata.py` (both): removed `"ox-alpha": 1_048_576` block + all "Ox Alpha"/stealth comments.
  - `agent/reasoning_timeouts.py` (both): removed `("ox-alpha", 300)` reasoning-timeout tuple + comments
    (kept `x-preview-f-free`).
  - `.hermes/cache/reasoning_caps.json`: removed ox-alpha keys.
  - `.hermes/cache/openrouter_model_metadata.json`: removed `stealth/ox-alpha` + `ox-alpha`, added
    `poolside/laguna-s-2.1:free` + `laguna-s-2.1` with live OpenRouter metadata (ctx 262144, pricing 0/0).
  - `website/static/api/model-catalog.json` (mirror): id `stealth/ox-alpha` → laguna (deduped).
  - Untouched on purpose: go-relay `ox-alpha-free` slug (real model on the Go relay, separate concern) and
    historical logs (`audit/`, `auto_fix_sessions.jsonl`, `.claude/projects/*` transcripts).
- Verified: zero residual `stealth/ox-alpha` in live code/cache, `py_compile` + `json.load` all pass,
  free tier now leads with laguna-s-2.1:free.
- **Found & fixed a latent bug**: `system_doctor._restart_gateway_service` called bare `s6-svc` which is NOT
  on the container exec PATH → a "real" gateway-down event would have failed to restart. Now uses
  `/command/s6-svc`. (`s6-svstat`/`s6-svc` live under `/command` inside the container.)
- Bounced `gateway-default` (`/command/s6-svc -r`) to reload the catalog; confirmed fresh pid (57827).
- Constraint reminder: `:free` OpenRouter models are still 429-limited for this account (free-models-per-day)
  until credit top-up; laguna is at least a valid, catalog-backed free target for when limits reset,
  unlike stealth/ox-alpha which no known endpoint serves.