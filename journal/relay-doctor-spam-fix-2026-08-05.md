# Relay — system_doctor Telegram spam fix (2026-08-05)

## Context
User asked why so many "doctor:" Telegram notifications and to suppress the ones with
no user action. The Telegram dump showed dozens of identical
`doctor: Graph stale/empty: collaborator-memory (0 nodes, ...)` messages.

## Diagnosis
- Sole sender: `~/.hermes/scripts/system_doctor.py`, scheduled via
  `Job("system_doctor")` in hermes_scheduler.py (every 30 min).
- `check_graph_health()` calls `homelab_graph.crg_graph_health(stale_hours=48)` and
  re-emitted the SAME stale/empty finding every run.
- `doctor_state.json` only tracked `last_vacuum` — there was NO record of what had
  already been alerted, so identical messages were sent every 30 min with no dedup.

## Fix (commit `6112114`, pushed to chaguli/AgentChaguli.git master)
- Added `last_notified_fp` (fingerprint = sorted "\n".join(noteworthy findings)) to
  doctor_state.json.
- `__main__`: only calls send_alert when the fingerprint CHANGED since last run.
  Ongoing conditions are reported once then silent until they resolve or change.
- All-clear path resets the fingerprint so a future new issue re-alerts once.
- Established baseline fingerprint on first run (collaborator-memory stale) so next
  scheduler runs are silent. Verified: second run would-send=False.

## Result / behavior
- Each distinct doctor issue: alerted exactly once, silent until change.
- When collaborator-memory graph gets re-synced (nodes/timestamp change), fingerprint
  changes → one re-alert, then silence again. New issues (dead daemon, 409, etc.)
  still alert immediately.

## Related notes
- The "no user action" pattern (persistent stale CRG graph) is exactly what dedup
  handles: report once, then stay quiet. Does NOT need a whitelist.
- system_doctor also still restarts dead daemons + vacuums DBs (routine items are
  already filtered from Telegram via ROUTINE_PREFIXES).