# Relay — Jenny: structural fixes (natural-language fallback, board reconciliation)

## Fixes applied 2026-09-14

### 1. Natural-language → rigid-command mismatch (the root failure cluster)
**Problem:** loop agents execute delegated task titles as shell commands via
`shlex.split(title)`. The orchestrator/LLM writes titles like "Analyze audit
logs…", "Check disk usage…" — baseplate/finlay/connector fail with
"Unknown command: Analyze". 16 failed tasks + 10 phantom human-attention
tasks resulted.

**Fix in `agent_loop.py` (deployed to both `agents/` and `scripts/`):**
- `consume_assigned_tasks`: on first `rc!=0`, calls hop gateway to
  *translate* the natural-language title into the domain script's real
  subcommand args (e.g. "Audit the docker containers…" →
  `check docker hermes-container disk disk-usage`), retries once.
- If still failing → marks source `done` (stops the re-fail spiral) +
  posts a ready `❓ … couldn't run — needs input` human-attention task on
  jenny (owner=rohit) instead of `failed`.

**Verified:** "Audit the docker containers and report disk usage" →
translated → baseplate `done` with proof "check done — 1 alerts".

### 2. Loop re-escalation loop on ❓ human-attention tasks
**Problem:** ❓ tasks (area=jenny) were re-delegated by Jenny back to the
same agent → same failure → new ❓ → infinite.

**Fix in `jenny_chief.py`:** `_execute_intent` detects `title.startswith("❓")`
→ acks (sends "Seen:" + marks done), never re-delegates.

### 3. Board reconciliation
- Discarded 6 hallucinated early-review tasks (area lab/backup/drainage).
- Marked 10 "Unknown command" failures as `done` + posted human-attention
  tasks; 8 acked by Jenny, 1 manually closed.
- Deduped 19 duplicate ready tasks (finlay x10, calendula x6, connector x6
  → kept one canonical each).
- Closed 16 ghost `init:*` objectives from the first hallucinated review.
- Board: 102 tasks → 77 done / 25 ready (all legitimate: bills, birthdays,
  IDs, HVAC, inference probe, backup-volumes TIMEOUT).

## Remaining board items
- `[backup] backup-volumes FAIL` (TIMEOUT 30s) — needs retry/fix
- 2 `summary` ready tasks (calendula/connector) — benign, domain scripts
  re-post summaries each cycle (benign noise)
- `hey jenny -` ready (old directive, TTL expired, still open) — can close

## Open gap: other agent's `import-gmail` + `inbox-zero` claims
`home-hp-opencode` claimed import-gmail/inbox-zero on the bus but Jenny
already ships Gmail perception. Needs coordination — who owns the inbox
pipeline? Flagged on the board via `coordination` channel.