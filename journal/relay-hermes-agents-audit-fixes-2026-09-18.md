# Relay — Hermes Agent Thread Audit + Fixes (2026-09-18)

End-to-end trace of every agent thread (8 domain agents + agentbus + Jenny +
homelab + mind_loop + orchestrator). Objective: close bugs, keep agents
LLM-determined within guardrails, and remove phantom/dead work. Final state:
all 13 units active with 0 restarts, regression 7/7, every agent check rc=0.

## Domain agents (agent_loop.py + agent_frame.py + per-domain scripts)

- **agent_frame.py**: rewrote the 593-line file — the same definitions
  (`bridge_send`, `load_store`, `save_store`, `playbook_priorities`,
  `upsert_task`, …) were byte-identical duplicated ~8× with last-definition
  winning. Single clean module now (~200 lines), every agent still passes.
- **NameError class of bugs** (key accessed unquoted, leaking loop vars or
  undefined names — each `check` cycle would throw, get swallowed by the
  agent's try/except, and silently report stale data):
  - finlay.py: `item.get(period, monthly)` → `item.get('period','monthly')`
    (2×, was rc=1 on every cycle — the audit's single most-loud bug).
  - housekeep.py: missing `import pathlib` made the HA-token probe a silent
    no-op; unquoted `item.get(name|kind)` in check/upsert/warranty paths.
  - calendula.py + connector.py: `item.get(kind)` leaked the loop variable as
    the key → `[None]` board titles every cycle; unquoted report() keys.
  - courier.py: nested-quote f-string normalized (3.12+ syntax, now 3.11-safe).
  - bus_monitor.py: `J.load`/`J.dumps` were NameErrors — the event_driven.json
    counter was dead (used `json.load`/`json.dumps(..., indent=2)`).
- **agent_loop.py**:
  - `decide_action()` rewritten: deduped the duplicated nested loop, added
    `known_subcommands()` (regex over the domain script's dispatch chain),
    validated LLM subcommand choices, coerced unsupported → `['check']`
    (verified via driver: LLM hallucinated `add_check` → coerced, rc=0).
  - `cycle()` now falls back to `check` when a non-check action fails (reason
    records the attempted action).
  - Priority sort honor `_PRIORITY_RANK` instead of the old string compare
    (behavior on Python 3 is not stable sort by string → was wrong).
  - Evolution prompts now embed the last 3 **real** reflections (was
    arbitrary/self-selected context) — grounded, per-agent evolution.

## mind_loop + mind_loop_integration

- **`plan_intelligence` was stripping every plan's payload** — its "safety"
  re-normalization kept only `action/content/priority` (+4 cosmetic keys), so
  real `run_command` plans executed as `subprocess.run("", shell=True)`
  no-ops, and `/send`-confirmation plans lost `requires_confirm`/`proposal_id`/
  `tag`. Now preserves the full plan dict; only defaults missing keys. This was
  the root cause of the empty-command run_command execution.
- **Fail-closed action gate** (was a no-op: `from guardrails import
  Guardrails, Policy` ImportError → `_guardrails = None` silently). Now uses
  the real shared `guardrails.load_guardrails("mind_loop")` and an explicit
  read-only diagnostic allowlist (git status/rev-parse, df, free, uptime,
  kopia snapshot list, ls -la, cat /proc/meminfo + the exact commands the code
  generates). `run_command` off the allowlist (or with a shell-danger token) is
  blocked; unknown actions are blocked. Blocks aggregate to one WARN line per
  cycle (no per-plan spam) and are applied at the ACT stage, so the
  orchestrator never even sees an unauthorized plan. Non-shell plan actions
  (send_telegram / add_task / create_event / send_email) stay allowed.
- **Phantom proposals removed** (`_propose_authoring_action`):
  - Email reply drafts now require a **real recipient** from today's digest
    (parsed `alerts_inbox.jsonl` as the JSON array it actually is; the header
    "⚡ *Actionable* (3)" has no addresses so nothing fires today). The old
    code emailed `vendor@example.com` whenever content contained
    "actionable"/"invoice"/"payment".
  - The recurring "Address actionable emails" +2-day calendar block is gone
    (it re-proposed every cycle while a calendar event was upcoming).
  - The wellness branch read a signal nothing ever populates — removed.
- **`observe_email`** now parses the whole-file JSON array and surfaces
  per-record actionable summaries + extracted sender addresses (grounded).
- **`observe_telegram_history` removed** — it spawned `grep` on agent.log every
  cycle and its result was never consumed anywhere.
- **HN trending fetch throttled to hourly** (was every 5-min cycle ≈ 288
  requests/day; `hn_trending` is still consumed via GraphRAG every 3rd cycle).
- Pre-existing PEP 701 nested-quote f-strings normalized to 3.11-safe form.

## Jenny (reactive chief) — retry gap closed

- **`reactive_cycle` marked a directive handled BEFORE executing it.** If
  `decide()`/`_execute_intent()` blew up, the key stayed marked → the bus task
  sat "ready" forever and was never retried. Mark-handled now happens only
  AFTER a successful intent execution; a double-failure (LLM + fallback) just
  notifies "will retry" and leaves the task ready + unhandled, so the next SSE
  wake / periodic cycle picks it back up.
- Verified the full reactive command chain is bounded end-to-end:
  `jenny_llm.validate_intent` (tools allowlist, roster-only delegations/steps,
  spawn/retire sanity) → `_run_tool` prefix allowlist + `_SHELL_BAD` regex →
  bounded `_run_cmd`. The periodic path only executes fixed executor actions
  (no arbitrary shell).

## Verification

- `py_compile` clean on every edited file; `ruff --select F821,F841,F811`
  clean (only pre-existing `ev_span` unused-variable).
- Driver tests: guardrails gate blocks `rm -rf /` and `curl …|bash`, allows
  every read-only diagnostic; `_propose_authoring_action` returns None when
  the digest has no real sender; agent_loop coercion + fallback paths rc=0.
- Live: all 13 units active, NRestarts=0; all 8 domain agents log
  `executed check: rc=0` (finlay no longer rc=1); mind_loop cycles #8721/8722
  = 15 actions each, zero guardrail blocks (actions went 10→15 after the
  plan-stripping fix — the diagnostics now actually run). Regression 7/7.

## Files changed

`agent_frame.py`, `agent_loop.py`, `{finlay,housekeep,calendula,connector,courier}.py`,
`bus_monitor.py`, `mind_loop.py`, `mind_loop_integration.py`, `jenny_chief.py`.

## Notes / not fixed

- Digest "actionable" items carry no sender addresses today, so no email reply
  drafts are generated — once the digest carries addresses, the grounded
  proposal path engages on its own (that's the design; no phantom).
- `agent_orchestrator` specialist sub-agents still run for each plan (LLM
  cost); could short-circuit pure-shell diagnostics, left as-is — the
  boundary is gated, behavior is by design.