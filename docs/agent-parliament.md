# Agent Parliament, Experience Modules & the Human 6th Vote

> Canonical doc — keep in sync with `~/.hermes/scripts/{hermes_scheduler,decision_council,council_speaker,human_overrides,telegram_reply_listener,experience_builds,council_vote}.py`.
> System runs on the **host** (home-hp), not in a container, under `rohit`. Last updated 2026-09-04.

## What it is

A governance layer on the homelab: autonomous agents propose mitigations for detected failures and need a **qualified majority** before committing actions. Four "experience" modules act as deliberation members; the **human is the 6th vote** whose approval or rejection of sensitive (personal-data) actions is captured by ballot.

## Components

### Scheduler (`scripts/hermes_scheduler.py --daemon`)
Unprivileged cron-style loop on the host. Jobs registered in `define_jobs()`; each runs on a cadence with a timeout. Currently scheduled flow (log order at start):
`council_speaker` → `council_member_votes` → `tg_reply_listener` → tally (`decision_council --vote`) → `commitment_executor` → experience-module daily jobs → `self_correction`/`memory_sync`/`proxy_watchdog`/`circuit_breaker` maintenance.

**Operational notes**
- Relaunch (proven): `sudo -u rohit bash -c "exec nohup /usr/bin/python3 -u /home/rohit/.hermes/scripts/hermes_scheduler.py --daemon </dev/null >/tmp/sched.log 2>&1 &"`.
- **DANGER**: `pkill -f "hermes_scheduler.py --daemon"` matches the launching shell too. Use the bracket pattern `hermes_scheduler[.]py` **and** run kill vs. relaunch in separate SSH calls.
- A **watchdog can auto-relaunch** the daemon. Two daemons at once = two pollers on the same Telegram bot = getUpdates 409 conflicts. Always verify a single PID after any restart.

### Parliament flow
1. **Speaker** (`council_speaker`) — reads `unified_memory.db` `outcomes` for failures in `COUNCIL_WINDOW_HOURS` (default 24): `postgres_restart_failure`, `gene_backup_failure`, `alerts_source_down`, `notes_journal`, … → proposes one remediation `restore <target>` per failure → ids inherit the failure id.
2. **Members vote** (`council_member_votes`) — the 5 experiences write a slate `state/decision_votes.json`:
   `{proposal_id: {"action_key", "proposed_at", "votes": {member:0/1}, "members":[...], "quorum":3, "gene", "target", "failures"}}`.
3. **Tally** (`decision_council.py --vote`) — quorum = floor(members*2/3) + 1. Gate:
   - **yes ≥ quorum** → `human_override` gate → `personal` actions → **held**; else `enqueued`.
   - **held personal** → `human_overrides.register_ballot` → Telegram ballot with **`Ballot #<hex8>`** where `hex8 = sha1(action_key)[:8]`.
   - Decision rows written to `decision_register` (id, proposal_id, action_key, scale, gate, status, created_at, decided_at); the proposal is **popped from the slate** when finalized (the slate does not accumulate history).
4. **Human 6th vote** — the owner replies 👍/👎 to the ballot (any explicit `yes/no` word or token). Signal lands in `state/human_votes.json`. Next tally: approved → `enqueued-human-approved` → `commitment_queue` → `commitment_executor` → `data/commitments.json` `active[]`; rejected → `rejected-human-expired`/`rejected-human`.
5. **Commitment executor** — tracks active commitments, alerts on completion/overdue; does not blind-execute unknown actions.

### Ballot lifecycle (`human_overrides.py`)
- Token deterministic per action: `sha1(action_key)[:8]` (stable across re-pages).
- Fresh ballot: `pages=1`; tally **holds silently while young** (no 5-min flood).
- Stale (older than `HUMAN_BALLOT_TTL_HOURS`, default **72h**) → **re-page** `pages+1`.
- Stale **and** `pages ≥ HUMAN_BALLOT_MAX_PAGES` (default **3**) → **expire** → decision `rejected-human-expired`, ballot removed.
- `cleanup_ballots()` sweeps orphaned ballots.

### Telegram reply listener (`telegram_reply_listener.py`)
- Long-polls `getUpdates`, offset persisted to `state/tg_listener_offset.json`.
- Parses votes: yes/yep/approve/confirm/ok/go/👍 | no/nope/decline/deny/reject/👎/stop.
- `extract_ballot_token` matches `Ballot #<hex8>` or a bare 8-hex token.
- Resolution order: reply-to-quote token → explicit token in message → single pending-human key.
- **Fail-closed auth**: requires `TELEGRAM_HOME_CHANNEL` (may be `chatid:threadid`; validates `message_thread_id` when a thread is set); `TELEGRAM_ALLOWED_USERS` (numeric IDs, comma list).
- **Confirm circuit breaker**: per-vote dedup + burst cap (3 confirmations / 10 min) via `state/tg_confirmations.json`.
- Reads env from `.env` **dynamically** (tests can set it post-import).

### ⚠️ Bot-ownership conflict (architectural, live-verified 2026-09-04)
Hermes itself IS the Telegram bot and long-polls the **same token** the listener uses → two pollers = getUpdates 409; whichever grabs an update consumes it. In the live smoke test Hermes (not our listener) received the owner's ballot reply. **Any Telegram-reply-driven vote is therefore unreliable until resolved.** Two fixes, pick one:
1. **Dedicated parliament bot** (new token; listener polls it exclusively), or
2. **Hermes relays ballot replies** into `state/human_votes.json` (it already reads the `Ballot #` token and answered "6 votes in favor") — zero conflict. Recommended.
The CLI signal (`human_overrides.py --gate "<action>" --human-yes|--human-no`) is always available to record the 6th vote manually and is the mechanism used to close the live test.

## The 4 experience modules (deliberation members)

Each is a daily/adhoc build job + deliberative role; each contributes a scored vote `{yes/no/abstain, signal}`.

| module | build output | council role | correction route |
|---|---|---|---|
| `learning_integrator` | cumulative insights from chat history (learning.db) | knowledge vote | consent ballot (personal) / `[trial]` enqueue |
| `insight_engine` | episodic insights + gaps (insights.db) | pattern vote | same |
| `adversarial_engine` | risk-candidates (adversarial.db) | risk/peak-vote | same |
| `predictive_signals` | forecasts + confidence (signals.db) | prediction/temperature vote | same |

Narrative/reflection outputs (no correction routing wired yet): `soul_avatar` (weekly persona reflection), `life_radiator` (weekly life-work pulse), `state_verdict` (monthly auto-coach verdict that **does** route its top correction via `route_correction`, gated by env `EXPERIENCE_ROUTE_CORRECTIONS` (default "1") → personal → pending-human consent ballot; infra → `[trial]` enqueue).

### Correction routing (`human_overrides.route_correction(action, source)`)
- personal data → `pending-human` consent ballot (same ballot machinery).
- infra → `_enqueue` with `[trial]` tag in `commitments.json`.
- report flag: `experiences` state carries `correction_routed`.

## Data contracts

| Where | Shape | Written by |
|---|---|---|
| `unified_memory.db` → `outcomes` | id, source, timestamp (ISO-8601), target, details | speakers + tests |
| `unified_memory.db` → `decision_register` | id, proposal_id, action_key, scale, gate, status, created_at, decided_at | decision_council |
| `state/decision_votes.json` | slate dict (finalized proposals popped) | council_member_votes / council |
| `state/human_votes.json` | `{action_key: {vote, when}}` | listener / --human-yes CLI |
| `state/human_ballots.json` | `{hex8: {action_key, paged_at, pages}}` | human_overrides |
| `state/tg_listener_offset.json` | last update_id | listener |
| `state/tg_confirmations.json` | confirmation dedup/burst bookkeeping | listener |
| `state/commitment_queue.json` | `[{action, queued_at, source}]` | decision_council |
| `data/commitments.json` | `{"active":[{id,text,source,created_at}],...}`, `[trial]`-tagged for trials | commitment_executor |
| `data/alerts_inbox.jsonl` | JSON **array**: {severity,message,source,timestamp,delivered,requires_approval,actions,delivered_at} (real inbox `~/agentharness/data/alerts_inbox.jsonl`) | alerts_delivery / commitment_executor / email_intelligence |

## Manual operations / overrides

- Tally with a test window: `COUNCIL_WINDOW_HOURS=24 python3 ~/.hermes/scripts/decision_council.py --vote` (`.env` sourced on-box for Telegram paging).
- List open proposals: `COUNCIL_WINDOW_HOURS=24 python3 ~/.hermes/scripts/decision_council.py --list-open`.
- Record the human vote: `python3 ~/.hermes/scripts/human_overrides.py --gate "<action>" --human-yes|--human-no`.
- Confirmations/speaker rely on Telegram creds in `.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_HOME_CHANNEL` (`chatid:threadid`), `TELEGRAM_ALLOWED_USERS` (numeric IDs).
- Clean DB of test residue: `DELETE FROM decision_register WHERE source='decision_council'`; `DELETE FROM outcomes WHERE source IN ('test','live-test')`.