# Relay — Homelab Agent LLM-Driven Conversion (2026-09-17)

User directive: make the homelab agents as open-ended as possible with strong
guardrails, "less deterministic and more llm determined within guardrails" —
not hardcoded Python if/else scripts.

## What changed

`homelab_agent_autonomous.py` rewritten from a fully deterministic
check→plan→act rule script into a **guarded LLM-decided** agent:

- **OBSERVE/CONNECT stay deterministic** (sensing + insight extraction is
  context gathering, not decision-making).
- **PLAN is LLM-decided**: `_llm_decide()` asks the local hop gateway
  (`http://127.0.0.1:8083/v1/chat/completions`, `haiku-4.5`, temp 0.2, thinking
  off) for a strict JSON action array. Every action is validated by
  `_validate_action()` against observed signals + cooldowns before execution.
- **Deterministic fallback preserved**: when the LLM is unreachable or returns
  nothing valid, `_fallback_plan()` runs the old rule logic. Same pattern as
  the existing `agent_loop.py` / `jenny_llm.py` hybrid design.

## Guardrails (enforced regardless of LLM output)

1. **Action allowlist only**: `heal`, `verify_backups`, `clean_disk`,
   `apply_updates`, `notify`, `nothing`. No arbitrary commands.
2. **No LLM-supplied targets**: every executed command resolves to a fixed
   method; container/service names come only from observed signals, never LLM
   text (defense in depth, re-validated in `act()`).
3. **Per-action cooldowns** prevent churn loops: heal 30m, apply_updates 6h,
   clean_disk 2h, notify 15m (state, persisted).
4. **apply_updates "all"** requires `HOMELAB_ALLOW_FULL_UPGRADE=1`; default is
   security-only. Preconditions: updates must actually be available.
5. **clean_disk never uses `--volumes`** (data-destructive).
6. **notify** rate-limited + length-capped (400 chars).
7. **heal preconditions**: docker heal only when observed unhealthy; systemd
   only when failed services observed; agentbus only when down.

## Verified

- Compiles; single-cycle run: `LLM decided: nothing` (27 healthy containers),
  state recorded `planned_by_llm: true`.
- Fallback proven: dead hop URL → `LLM planner unavailable — deterministic
  fallback`, degraded-signal synthetic test produced heal docker + correct
  observed-only restart.
- Live service: `homelab-agent.service` cycles at 15 min now LLM-driven
  (`LLM decided: nothing`, cycle #353).
- Stale `BRIDGE_URL=http://127.0.0.1:9198` env (dead Round-5 duplicate-bridge
  port) removed from the unit; nothing referenced it.
- Regression **7/7 PASS**.

## Side note: old determinism had a latent crash

Old `homelab_agent.log` showed `cannot access local variable 'state'` on every
cycle — a latent bug in the old rule logic. The rewrite eliminates the class.

## Side fix: rclone config ownership

`gdrive-owned` regression check was failing 1/7: `rclone.conf` had become
**root-owned 600** (Sep 17 12:04 — the Round-6 off-site push runs rclone as
root via `RCLONE_CONFIG`). rohit's regression check couldn't read it. Fixed:
`root:rohit 640` so both root pushes and rohit checks can read it. 7/7 again.

## Files touched

- `/home/rohit/.hermes/scripts/homelab_agent_autonomous.py` — LLM-driven rewrite
- `/home/rohit/.config/systemd/user/homelab-agent.service` — dropped dead BRIDGE_URL
- `/home/rohit/.config/rclone/rclone.conf` — ownership root:rohit 640
- `/home/rohit/.hermes/state/homelab_state.json` — new `cooldowns` + `planner` provenance

## Open / next

- Same treatment, if user wants, for `jenny_agent_autonomous.py` /
  `jenny_chief.py` (same hybrid base exists).
- Watch one full outage cycle: LLM down + real degraded infra should still
  heal deterministically (already unit-proven; live-fire only when it happens).