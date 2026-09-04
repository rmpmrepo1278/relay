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
- Consider noise-reduction for council propose/tally messages once balloting is fully automated.