# Audit Slice 2 Complete — R5+R6+R8+R10

**Date**: 2026-08-21  
**Commits**: `a88c637` (main fixes) + `357517c` (autonomous_self restore)

All 10 findings from the codebase audit are now implemented across two slices.

## R5: Hoist guardrail to single enforcement point
- Extracted `ACTION_DOMAINS` to module-level constant in `mind_loop.py`
- Removed duplicate PLAN-phase guardrail check from `run_cycle()` (~10 lines)
- `execute_plan()` at line ~760 remains sole enforcement point
- Invariant: `ACTION_DOMAINS` appears exactly once; `_guardrails.check()` called exactly once

## R6: Consolidate n8n_bridge result shapes
- Added `ok_result(**kw)` and `err_result(msg)` constructors
- Rewrote `_fmt()` as status-first — no more probing `error`/`message` keys in priority order
- Fixed contradictory payloads in 5 handlers where `"status": "ok"` coexisted with non-empty `"error"` field
  - `docker-restart`, `docker-exec`, `host-exec` (×2), `service-restart` success
- Renamed `error` keys to `stderr` in success cases to avoid `_fmt` misinterpretation

## R8: Remove duplicate Prometheus rules + dead alert
- Deleted `services/prometheus/rules/alerts.yml` (stale copy of main `alerts.yml` with old SSL annotation)
- Removed dead `ContainerDown` alert group (watches `cadvisor` job going down — redundant with `CadvisorDown` in `service_alerts`)

## R10: Consolidate Telegram senders
- Created `scripts/lib/telegram_send.py` — shared module with `send_telegram()`, `is_duplicate()`, `mark_sent()`
- `cos_briefing.py` and `evening_briefing.py` now import from shared module
- Retry logic (3 attempts, 15s delay) and 6-hour dedup retained from best implementation
- `send_telegram.py` (stdin pipe) left untouched — different use case (non-cron, one-shot)

## Autonomous_self restore
- `autonomous_self.py` was accidentally archived during Slice 1 but still imported by mind_loop
- Restored from `archive/autonomous_self.py` to `.hermes/scripts/`
- mind_loop running clean: zero errors in cycles 3581+

## Full audit completion
| Finding | Status | Commit |
|---------|--------|--------|
| R1: Dead commitment step | ✅ | `98c24da` |
| R2: Duplicate dispatch | ✅ | `98c24da` |
| R3: Narrative memory hot-path | ✅ | `00e2f86` |
| R4: Phantom eval loop | ✅ | `98c24da` |
| R5: Guardrail dedup | ✅ | `a88c637` |
| R6: Result shapes | ✅ | `a88c637` |
| R7: Inventory N+1 cache | ✅ | `00e2f86` |
| R8: Prometheus dedup | ✅ | `a88c637` |
| R9: Dead scripts | ✅ | `98c24da` |
| R10: Telegram consolidation | ✅ | `a88c637` |
