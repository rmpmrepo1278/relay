# Relay — Jenny: Full Chief-of-Staff (Reactive LLM Core + Proactive Officer's Review)

## Goal (Rohit, refined)
Jenny must be always-on with **instant reactions** (LLM request/response), able
to **execute herself OR delegate**, **spin up / retire specialist agents**, hold
**authority over the team**, **coordinate multi-agent tasks**, and — critically —
be **proactive**: connect the pieces (Gmail, homelab automations, inference
performance, open items on Rohit's end) and follow through autonomously, like a
real chief of staff.

## What was built & deployed (all under `~/.hermes/scripts/`, synced to repo `code/scripts/`)

1. **`jenny_llm.py`** — LLM judgment core. Calls hop gateway
   (`haiku-4.5` → poolside/laguna-s-2.1:free). Turns a directive + board context
   into STRICT-JSON intent: `chat|execute|delegate|coordinate|spawn|retire`.
   Deterministic keyword fallback if gateway down → Jenny never ignores Rohit.

2. **`jenny_chief.py`** — the new daemon (`jenny-agent.service` now runs this).
   Two brains:
   - **Reactive**: SSE listener on agentbus `/stream`. Any `task-add` (bridge
     `/jenny`, Gmail bridge, other agents) wakes Jenny instantly → LLM decide →
     execute (chat/execute/delegate/coordinate/spawn/retire) → mark bus task
     done with proof. Verified: `disk usage` directive → delegate to baseplate
     in ~30s; `spin up pilotwatch` → Jenny spawned the agent herself.
   - **Periodic**: inherited deterministic OBSERVE→PLAN→ACT cycle every 30m
     (safety net + briefs) + `proactive_review()` every 6h.

3. **`agent_manager.py`** — safe spawn/retire. Name must match
   `^[a-z][a-z0-9_]{1,19}$`, no collisions, protected core agents refused
   unless `force=True`. Spawn creates `agents/<name>.py` = generic watchdog
   domain script (LLM output is only name/role/triggers — **never code**),
   `agentbus/memory/<name>.md` personality, `agent-<name>.service` systemd unit
   (`agent_loop.py <name> --interval 300`). Retire stops+disables the unit and
   archives script+personality (`*.retired`).
   - Verified: spawned `watchdog` (live on bus, loop working) → retired cleanly.
   - Verified via Jenny's own LLM authority path: she spawned `pilotwatch` then
     I retired it to keep the roster lean.

4. **`jenny_perf.py`** — inference health probe. Measures hop gateway latency
   (probe: 0.56s = healthy), red lines 5s warn / 12s crit, compares to the
   benchmark store baseline. Feeds the review so "inference tokens/sec slow"
   becomes an escalatable initiative.

5. **`jenny_gmail.py`** — Gmail perception. Uses the EXISTING Google OAuth
   stack (`~/.hermes/gmail/{credentials,token}.json`, built a service with the
   token's own scopes to dodge gmail_reader's `gmail.labels` invalid_scope).
   Reads unread inbox → LLM classifies
   `actionable|follow-up|informational|ignore` → actionable items become
   `area=<agent_hint>` bus tasks owned=rohit → SSE wakes Jenny. Seen-ids in
   `~/.hermes/state/jenny_gmail_seen.json`. Verified: 8 scanned; tightened the
   prompt so promos/deals/credit-card pitches are `ignore` (1/8 actionable after
   tightening). Bot account: `rohitmishra1278@gmail.com`.

6. **`jenny_ops_review.py`** — the Officer's Review loop (the proactive brain).
   gather() = board+presence+journal+perf probe+gmail scan → LLM synthesizes
   up to 3 **initiatives** (title/owner/first_step/priority/why) → act()
   dedupes (seen-file, 7d window) → delegates first_step as bus task + records
   objective → digests to Telegram topic 10000. **LLM-safety**: owner
   validated against hardcoded roster; unknown owners dropped.
   - First run hallucinated ("lab board drainage") — fixed with domain
     vocabulary in the prompt + owner whitelist. Second run returned sane
     initiatives (baseplate audit, inference perf, finlay/gmail).
   - BoB first-run junk tasks (`lab`, `backup`, "drainage") were reconciled →
     marked `failed` with proof.

7. **Bridge** (`n8n_bridge_server.py`, restarted): smart `/team`, `/jenny
   <directive>` → bus task area=jenny owner=rohit, `/delegate <agent>` → bus
   task (legacy fallback to Claude). Earlier deployment had silently reverted to
   the legacy bridge; redeployed the smart master + backed up legacy.

## Verified end-to-end
- Reactive: `/jenny check disk usage and send one-line summary` → SSE wake →
  LLM decide → delegated to baseplate → task `done` (proof `delegated_to:baseplate`).
- Spawn via Jenny's LLM path: `pilotwatch` created + active.
- Coordinate: "check backend disk usage THEN update vault backup digest" →
  LLM chose `coordinate` with plan
  `baseplate:check disk → vault:update digest`; source task done.
- Retire: watchdog + pilotwatch → stopped, archived, presence `idle`.
- Perf probe healthy 0.56s; Gmail 8 scanned / 1 actionable after tightening.

## Files
`code/scripts/`: `jenny_llm.py`, `jenny_chief.py`, `jenny_perf.py`,
`jenny_gmail.py`, `jenny_ops_review.py`, `agent_manager.py`,
`_watchdog_agent_template.py`, `jenny_agent_autonomous.py` (added
`_mark_task_ended` POST-JSON), `n8n_bridge_server.py` (smart bridge, backed up
legacy).

## Caveats / next
- Review hallucination risk handled (vocabulary + roster whitelist), but review
  quality should be rechecked after a few real reviews.
- Spawned domain scripts are generic watchlists (check/report/add). For a
  spawned agent to do real domain work, give it a real playbook personality or
  wire hop-based reasoning — next iteration.
- Gmail currently only surfaces NEW items (seen-state). A periodic
  re-scan cadence is via the 6h review; consideration: resurface follow-up
  items near due dates.

## Commit
2026-09-14 — beyond orchestration-layer deployment.