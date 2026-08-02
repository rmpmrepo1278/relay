# Relay Journal — 2026-08-02

## Session: make the homelab a truly autonomous self-healing stack

Drove the auto-heal / monitoring stack from "alarm spam + silent failures" to
green. Everything committed + pushed (`agentharness`, home repo `chaguli/master`).

## Root-cause fixes
1. **Autoheal notification spam** (agentharness `0d46b5d`): `{{.State.Health.FailingStreak}}`
   template never rendered (`<no value>`) → garbage in every alert. Fixed template
   + `<no value>` → `none` coalesce + delegate/scheduler timeouts (120→960s,
   180→1000s) with `start_new_session` + `killpg`.
2. **consolidated_health.sh integer bug** (`grep -c ... || echo 0` prints "0\n0"
   under `set -euo pipefail`) → killed every 5-min cycle; fixed `|| true`.
3. **Cost guard false alarm**: missing `.orbit_cost_state.json` → baseline 0 →
   every run flagged a real $32.86 OpenRouter spend as "CHARGE DETECTED". Wrote
   baseline → ALL OK.
4. **soul_overlay_gen.py**: stray heredoc `EOF` token (NameError) at file end, removed.
5. **CLAUDE.md was missing** → doc_sync/doc_drift were false-failing; restored
   from `87c5e8e^` (553 lines).
6. **Dead jobs/units removed**: `traefik_sync` (script deleted in audit, configs
   static), `tmux-opencode.service` (no tmux), `health-dashboard.service`.
7. **Healthchecks server was DOWN at 127.0.0.1:8004** → all canary pings silently
   failed. Revived via compose/apps.yml, chowned data dir to uid 999, created
   admin + project + 10 checks with the exact UUIDs from `hc_uuids.sh`, verified
   last ping HTTP 200.
8. **Scheduler `_hc_ping` bug**: used route `/hcup/{uuid}` (wrong — must be
   `/ping/`) AND omitted `Host: healthchecks.home` header (SITE_ROOT requirement)
   → every scheduler-driven canary ping 400ed silently. Both fixed; verified 200s
   in server logs. THIS was the real "autonomous" hole — the fixer's own pings
   never reported.
9. **State file hygiene**: scheduler never pruned state for removed jobs
   (traefik_sync/kopia_backup/kopia_volumes polluted failure reports forever) —
   added pruning in `run_due`. Also `last_run` was naive local while job entries
   were UTC-aware; now UTC-consistent.

## Verified green
- scheduler single daemon (systemd), consolidated_health + 16 core jobs success
  in recent window; 0 failed systemd units; disk 37%; 21Gi RAM free.
- scheduler state prunes stale keys; healthchecks pings 200 in logs.

## Notes / gotchas
- SSH display mangles `hc_ping.sh` → `ln` etc. Use `od -c`/`cat -A` to verify
  bytes. Heredocs over ssh corrupt → write file then `scp`/`python3 file.py`.
- State file is authoritative over scheduler.log for job status.
- Remaining backlog: 117 stale agentharness infra tests; healthchecks compose
  uses `${HC_SECRET_KEY:-changeme}` defaults → move to .env; ARCHITECTURE/README
  docs still reference old fixer behavior.
