# Doubled-path leak (~/.hermes/.hermes) — root cause fixed (Sep 17 2026)

## Symptom
Stale tree at `~/.hermes/.hermes/` containing `kanban.db`, `data/unified_memory.db`
(0 bytes), `data/telegram_throttle.json`, `data/telegram_dedup.json`,
`data/commitments.json`, `state/`. A leftover from a prior audit round we hadn't
closed; its `kanban.db` kept getting touched (06:17 daily).

## Root cause (fully traced)
The `n8n-bridge` container mounts host `~/.hermes` at `/opt/data` and sets
`HOME=/opt/data`, `HERMES_HOME=/opt/data`. Two mechanisms produced the doubled
path:

1. **Legacy writes (pre-fix era, Sep 12–14 + 00:03 Sep 17).** In-process
   imports in the bridge (`n8n_bridge_server.py:588`) computed
   `HERMES_HOME = Path.home() / ".hermes"` = `/opt/data/.hermes` = host
   `~/.hermes/.hermes`. `commitment_tracker.py` (DATA_FILE) and
   `commitment_interceptor.py` (sys.path) were NOT HERMES_HOME-aware.
2. **Ongoing re-toucher (today 06:17).** `db_integrity_check.py:75`
   `HERMES_HOME.rglob("*.db")` recursively descended into the stray nested
   tree and opened its `kanban.db`, recreating `-shm`/`-wal`. `system_doctor.py`
   `Path.home().glob(".hermes/**/*.db")` had the same recursion risk.

## Fixes (all live)
- `commitment_tracker.py` + `commitment_interceptor.py` now use
  `Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))` — the same
  pattern already applied to `narrative_memory.py` / `personal_model.py`.
- `db_integrity_check.py` skips any db whose relpath from HERMES_HOME begins
  with `.hermes` (the doubled-path subtree).
- `system_doctor.py` skips `/.hermes/.hermes/` in the glob walk.
- `n8n-bridge` container restarted; in-container check confirms
  `DATA_FILE = /opt/data/data/commitments.json` (canonical, host
  `~/.hermes/data/`) not the doubled path.
- Verified: `/commitments` canonical file updated 09:37 post-fix; no new
  writes to the doubled path across 3 × 5s monitoring rounds.
- Stale tree quarantined to `~/.quarantine/hermes-doubled-path-20260917/`
  (moved, not deleted — recoverable if any state mattered; cursory check: both
  kanban DBs had 0 tasks, unified_memory.db 0 bytes).

## Verification
- `db_integrity_check.py` → 45/45 OK (2 nested *.db now skipped), exit 0.
- Regression 7/7 PASS.
- Services: hostctl active, ports 9107 (agentbus) / 9199 (n8n-bridge) / 9201
  (hostctl) listening; n8n-bridge container Healthy.
- Remaining note: `_crg` in bridge (line ~1566) uses host-side
  `Path.home()/".code-review-graph"/"registry.json"` — safe because it is
  routed through hostctl (host HOME). No other literal doubled-path references
  remain in `scripts/*.py` or collaborator-memory copies (all hardlinked,
  auto-synced).

## Files changed
- `/home/rohit/.hermes/scripts/commitment_tracker.py`
- `/home/rohit/.hermes/scripts/commitment_interceptor.py`
- `/home/rohit/.hermes/scripts/db_integrity_check.py`
- `/home/rohit/.hermes/scripts/system_doctor.py`
- (hardlinked mirrors under `collaborator-memory/code/scripts/` auto-synced)