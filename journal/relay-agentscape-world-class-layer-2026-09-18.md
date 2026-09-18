# World-class layer (agentscape) + heavy-lifter direction — implemented (Sep 18 2026)

Rohit asked the architecture question: full Hermes agents with minimal
guardrails vs. the current thin bespoke fleet. Verdict: keep the thin fleet as
the cadence layer; raise its REACH inside the enforced envelope; stand up
full-Hermes "heavy lifters" for complex/human-in-the-loop work. Then: "complete
the in-flight work and shape the heavy-lifter design."

## What shipped (in-flight work completed)

New shared module `~/.hermes/agents/agentscape.py` (fail-open everywhere;
decision ledger unified with mind_loop's `data/decision_ledger.jsonl`):

- **A1 two-tap** `critique_decision()` — second-model review of high-impact
  actions before they execute. Verified live: benign `check` approved; ungrounded
  `apply_updates` REJECTED with reason ("not grounded to observed signals").
- **A2 verify-after-act** `verify_target()` (health-recheck for `heal`) +
  `record()` — every autonomous action now lands in the unified ledger with
  outcome + evidence + risk flag.
- **A3 outbound critique** `critique_message()` — last-line defense on the
  outbound send path. Verified live: "All systems nominal, nothing to report"
  GOO rejected (the exact class of noise from Round-10).
- **B6 GraphRAG context** `roster_context()` — GraphRAG query + memory grep
  (live: returns real context). **B5 web_search** — Serper/Brave provider-ready;
  keyless sources all dead (DDG serves bot-challenge pages), documented:
  mechanism ready, add `SERPER_API_KEY` or `BRAVE_API_KEY` to `.env` to light it.
- **C7 reflection rollup** `rollup_reflections()` — archives old reflection.jsonl
  entries to a per-agent learnings file on a 100-cycle cadence.
- **D9 digest** `digest_payload()` / `send_digest()` (+ anomalies from
  `analyze()`) + systemd user timer `hermes-agent-digest.timer` daily **05:45**
  to personal topic 10122; `scripts/agentscape_digest.py`.

Wiring:
- `agent_loop.py` (roster ×8): `_LOW_RISK_SUBS` gate → two-tap on anything else;
  ledger record after execute; reflection rollup at cycle %100; delegated-task
  `result` (D8). Live commit: courier `check → success` in ledger.
- `autonomous_agent.py` (homelab/jenny base): send-path critique; two-tap on
  `heal/apply_updates/clean_disk/notify`; ledger + verify-after-act per action.
- `jenny_chief.py`: ledger trace of every reactive tool call (`blocked`/`sent`/`added`).
- `mind_loop_integration.py`: overlay keep/defer decision recorded to ledger.
- `agentbus.py`: `/task op=set` accepts `result` field (report-back for D8).

Verified: py_compile clean on all 6 files; isolated battery green; live roster
cycle green; all 12 units restarted active; **regression 9/9 PASS**; digest
timer armed. Fixed en route: `.format()` ate literal JSON braces in the two
critique prompts (KeyError class); DDG scrape was dead → keyed providers.

## Heavy-lifter design (next round — shaped, not started)

1-2 full Hermes `AIAgent` cores, on-demand only, for research/multi-step work
where a human is present. Not a replacement for the fleet:
- **`hermes` gateway already exists** (skills + web + terminal + delegation +
  caching) — the heavy lifter is a *mode*, not a new binary. Shape: a gated
  CLI/slash entry point that spawns a session with the DANGEROUS toolsets
  disabled (`terminal`, `execute_code`, `delegate_task`, `browser`); enable
  `file`/`web`/`search`/`skills` only; high blast-radius → human confirm.
- **Delegation path**: fleet posts a task to agentbus with
  `owner=hermes-heavy`; a dedicated dispatcher turns board-ready tasks into
  gateway sessions (`hermes run` / gateway API), one job = one session (caching
  intact per job), reports `result` back onto the task (D8 field just shipped).
- **Guardrails**: toolset-gating (not model-behavior promises) + CRG
  blast-radius → proposal + no background/`terminal(bg=True)` + per-session
  budget + human watched via Telegram topic.
- Fleet keeps ALL current autonomy; heavy lifter is the *capability escalation
  path*, gated by design. See AGENTS.md Round-12 note.