# Relay — Jenny Agent LLM-Driven Conversion (2026-09-17)

Follow-on to the homelab conversion: apply the same "less deterministic, more
LLM-determined within guardrails" treatment to Jenny (Chief of Staff).

## What changed

### jenny_llm.py — guardrail pass on the reactive intent path
- New `validate_intent()`: bounds every free-text vector the LLM emits.
  - Tools → allowlist only (`send_telegram`, `create_bus_task`, `run_command`),
    args clamped to 300 chars, capped at 4.
  - Delegations/steps → targets must be in the team roster (`TEAM`), tasks
    non-empty and ≤400 chars, delegations capped at 3, steps at 5,
    priority normalized.
  - Spawn → name must match `^[a-z][a-z0-9_]{1,19}$` + non-empty role
    (agent_manager still enforces the real spawn rules); invalid spawn name
    degrades to `chat`.
  - Retire → target must be in roster, never spawn-empty.
  - A `delegate`/`coordinate`/`execute` intent that loses every actionable
    payload (all targets dropped) degrades to `chat` so Jenny replies instead
    of half-executing.
- `decide()` now returns `validate_intent(parsed) or fallback_intent(...)`.
- Last-resort deterministic fallback no longer runs raw shell on the directive:
  the "no keyword match → execute run_command" arm is now a safe
  "delegate to homelab ops" arm.

### jenny_chief.py — close the arbitrary-shell hole
- `run_command` (the one shell escape hatch) is gated:
  - `_ALLOWED_COMMAND_PREFIXES` allowlist (systemctl status/is-active,
    docker ps/stats/images, kopia snapshot list/repository status, ps/free/df,
    uptime/date/whoami/hostname).
  - `_SHELL_BAD` regex denies `; & | ` $()` `>`, rm/mkfs/dd/shutdown/reboot/sudo rm.
  - Anything else → rejected + logged WARN. LLM can never pass arbitrary shell text.

### jenny_agent_autonomous.py — periodic cycle now LLM-determined
- `anticipate()` is now context-only (no side effects). Previously it directly
  delegated health checks and sent a Telegram "preparing brief" line — both
  hardcoded actions now flow through the planner instead.
- New `plan()`: LLM-first (hop gateway, haiku-4.5, same strict-JSON contract as
  homelab). Feed the org digest + fresh insights + forecasts; the LLM picks
  from an action allowlist.
- Guardrails (`_validate_plan`):
  1. Action allowlist only: send_telegram, coordinate_cross_agent, delegate,
     reply_chat, initiate_onboarding, generate_brief, nothing.
  2. **Every action except nothing/generate_brief must be grounded on a real,
     present insight (`ins_id`)** — no phantom actions from hallucination.
  3. `delegate` target must be a roster member; task non-empty.
  4. `reply_chat` only grounded on a `user_directive`; `initiate_onboarding`
     only on an `onboarding_request`.
  5. `generate_brief` only inside its 04:50–05:10 window.
  6. Per-action cooldowns (send_telegram 30m, coordinate 15m, delegate 10m,
     reply_chat 5m, onboarding 4h) → no churn.
  7. ≤6 plans/cycle. LLM-drafted replies capped at 400 chars.
- `_fallback_plan()` keeps the old deterministic keyword planning intact
  (LLM offline/malformed → same behavior as before).
- Planner provenance recorded in `reflect()`: `planned_by_llm`, actions, skips.
- **Early-return optimization**: zero insights + zero anticipations → return []
  without an LLM call. The 1-min periodic loop no longer hammers hop ~1400x/day;
  when something is actually actionable the LLM is consulted.
- Latent bug fix in the fallback: `check_agent` parsed the agent name from the
  **last word** of the insight content (grabbed "reporting"/"bus" instead of
  the agent). Now reads it from `dedup_key` (`missing:<agent>`).

## Verified
- Reactive path probes (LLM live): bill → delegate finlay; birthday gift →
  delegate connector; "retire pilotwatch" → chat (correctly refused); all
  delegation targets in-roster, tools allowlisted.
- Periodic LLM plan with synthetic insights → delegate finlay, `_llm=True`,
  guardrails enforced.
- Fallback path (dead hop): keyword planning still emits delegate homelab /
  delegate finlay (fixed agent-name parsing).
- Live daemon: cycle 203 `planned_by_llm: True` (LLM decided `nothing`),
  cycles 204+ short-circuit with 0 LLM calls when nothing to do (0.03s).
- homelab-agent + jenny-agent both `active`.
- Regression 7/7 (twice; one earlier single-check flake was the pre-existing
  tg-send throttle-timing class, unrelated to these agent changes).

## Files touched
- `/home/rohit/.hermes/scripts/jenny_llm.py` — validate_intent + safer fallback
- `/home/rohit/.hermes/scripts/jenny_chief.py` — run_command gating (+ re import)
- `/home/rohit/.hermes/scripts/jenny_agent_autonomous.py` — LLM periodic plan,
  context-only anticipate, reflect provenance, early-return, fallback fix
- `/home/rohit/.config/systemd/user/jenny-agent.service` — dropped dead
  BRIDGE_URL=9198 (duplicate-bridge port from Round-5)
- `/home/rohit/.hermes/state/jenny_state.json` — new plan_cooldowns + planner
  provenance

## Notes
- Reactive path (jenny_chief SSE watcher + jenny_llm.decide) was ALREADY
  LLM-driven before this round; the value-add here was guardrailing it
  (bounded tools/targets) and converting the deterministic periodic cycle.
- The 04:50–05:10 generate_brief window mirrors the old 4:55 deterministic
  trigger; LLM can now also choose it, but still only in-window.