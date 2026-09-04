# Date: 2026-09-04 - Human 6th vote now lands via Telegram reply

## What shipped
- human_overrides.py: _page_approval_ballot now emits a machine-readable "Ballot #<hex8>" line and registers state/human_ballots.json (token -> {action_key, paged_at}). Token = sha1(action_key)[:8] (deterministic, stable across re-pages).
- New scripts/telegram_reply_listener.py: long-polls bot getUpdates (offset in state/tg_listener_offset.json), resolves the action from (a) reply-quote Ballot #token, (b) bare token in body ("no 3f7a2c9e"), (c) unambiguous single pending-human action. Writes state/human_votes.json, consumes the ballot token, pages confirmation.
- **Fail-closed auth**: no TELEGRAM_HOME_CHANNEL -> accepts nothing; chat compared as id[:thread_id] split (supergroup format); TELEGRAM_ALLOWED_USERS is a comma list of numeric user ids.
- Scheduler job tg_reply_listener (*/1, timeout 45), added after council_member_votes in define_jobs(). Daemon restarted single instance (PID 1536650).

## Verification
- Unit: reply-to-ballot, bare-token direct msg, unrecognized text, wrong chat, allowlist (2 users/non-user/wrong chat), fail-closed all pass.
- Real E2E: seeded gene_backup_failure notes_journal x2 -> Speaker proposed -> 5/5 yes -> tally held pending-human + Ballot e6062c2f registered -> synthetic reply (real chat -100... + real sender from TELEGRAM_ALLOWED_USERS) recorded -> re-tally -> gate: enqueued-human-approved, queue = [restore backup notes_journal]. Ballot consumed.
- Post-test state restored to clean; daemon cycling tg_reply_listener success every minute.

## Notes / gotchas
- pkill -f "hermes_scheduler.py --daemon" matches your OWN wrapping bash -c command line (it contains the string) -> kills the launcher. Use [.] pattern AND a separate SSH call for kill vs launch.
- Telegram env in .env: TELEGRAM_ALLOWED_USERS (plural!), TELEGRAM_HOME_CHANNEL (may carry :thread suffix).
- Pending-human resolution reads decision_votes.json votes (quorum>=3 yes>=2) - same predicate the tally uses.