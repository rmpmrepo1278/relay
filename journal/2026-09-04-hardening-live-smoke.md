# Date: 2026-09-04 — Ballot lifecycle + live Telegram smoke test

## What shipped (hardening pass)
1. **Ballot lifecycle** (`human_overrides.py` + `decision_council.py`):
   - Ballots now carry `paged_at` + `pages`; `ballot_lifecycle()` decides fresh/repage/expired. Tally holds silently while a ballot is young (previously re-paged every 5-min tally = flood).
   - Re-pages after `HUMAN_BALLOT_TTL_HOURS` (default 72h), expires after `HUMAN_BALLOT_MAX_PAGES` (default 3) -> `rejected-human-expired`, decision marked rejected, ballot removed.
   - `cleanup_ballots()` sweeps orphan ballots; finalized proposals now LEAVE `decision_votes.json` (was accumulating forever, causing re-tally churn + wrong "pending" set).
2. **`route_correction(action, source)`** — experience-module corrections join the pipeline (personal -> consent ballot; infra -> [trial] enqueue). Wire existing: `state_verdict` (env `EXPERIENCE_ROUTE_CORRECTIONS=1` default). life_radiator/soul_avatar are narrative-only today.
3. **Confirm circuit breaker** (`telegram_reply_listener.py`): per-vote dedup + burst cap (3 confirmations / 10 min) via `state/tg_confirmations.json`. Fixed missing `datetime` import.
4. **Scan path fix**: `override_scan` resolution now reads the REAL inbox `~/agentharness/data/alerts_inbox.jsonl` (JSON array; writers: alerts_delivery/commitment_executor/email_intelligence), fallback legacy. Verified: 20 entries, 0 requires_approval. Also fixed `council_vote._adb_recent_incident` (was pointing at wrong file).

## Verified (all on-box, daemon STOPPED to avoid races)
- Lifecycle unit: fresh=pages1, tally-reentry silent (ledger md5 unchanged), stale repage pages1->2, exhausted+stale->expired+removed, orphan sweep, route_correction pending-human. Circuit breaker dedup+burst. All pass.
- Council integration: propose->5 votes->held pending-human pages=1 -> tally2 silent hold -> human YES via listener synth (real chat/sender ids) -> tally3 enqueued-human-approved, slate 0, ballot consumed. Expiry path -> rejected-human-expired, slate 0.
- ALL new code py_compiled; daemon restarted single instance, logs show council_speaker/tally/member_votes/tg_reply_listener/commitment_executor all success.

## LIVE Teleugram smoke test — RESULT: partial, key finding
Paged a real ballot "restore backup notes_journal  Ballot #e6062c2f" (creds from .env). Rohit replied YES for real.
- **Our listener NEVER captured it**: `state/human_votes.json` stayed {} and offset stayed {}.
- Root cause A: a watchdog auto-relaunched a 2nd scheduler daemon -> two daemons + Hermes' own Telegram poller all doing `getUpdates` on the SAME bot token -> 409 "terminated by other getUpdates request" for our listener; Hermes' poller won and consumed (acked/offset) the YES.
- Root cause B: **architectural** — Hermes itself IS the Telegram bot and long-polls the same token. Two pollers on one bot = permanent conflict; whichever grabs an update consumes it. A reply-vote listener can never be reliable this way.
- Resolution: recorded Rohit's confirmed YES via the CLI gate (`--gate ... --human-yes`, the legitimate 6th-vote signal) -> tally -> `enqueued-human-approved`, queue fill, slate drained. Then removed all smoke artifacts (queue/commitments/slate/ballots/DB rows) since "restore backup notes_journal" was a synthetic seed with no real restore behind it.

## Recommended follow-ups (architectural)
- **Give the parliament its own bot token** (e.g., `@CouncilBallotBot`) with `TELEGRAM_HOME_CHANNEL` = that bot's DM/supergroup; listener polls exclusively, no 409.
- OR **teach Hermes** (it already reads `Ballot #xxxx` and replied "6 votes in favor") to write ballot replies straight into `state/human_votes.json` via `human_overrides.py --gate <action> --human-yes/no`. Zero getUpdates conflict.
- Keep `rejected-human-expired`/`pending-human` semantics working either way.

## Gotchas
- `pkill -f "hermes_scheduler.py --daemon"` matches the launching shell too -> use `[.]` AND a separate SSH call for kill vs launch. Watchdogs may auto-relaunch a daemon mid-test; for safe manual DB tests, stop all daemons first.
- `human_overrides.py` was previously reading a WRONG inbox path (.jsonl was fine, location was not).