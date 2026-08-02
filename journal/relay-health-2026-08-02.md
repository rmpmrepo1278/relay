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
10. **Healthchecks checks were only half-wired**: 10 checks created but the
    scheduler's `Job` never assigned `healthchecks_uuid`; the hc_uuids.sh
    exports were defined but never parsed (would NameError). Added a
    `_load_healthcheck_uuids()` loader, wired health_dashboard /
    autonomous_fixer / morning_prep / morning_pipeline to their checks
    (consolidated_health self-pings in-script). Final healthchecks API state:
    consolidated-health, health-dashboard, autonomous-fixer all `status=up`
    with live pings; remaining 7 checks will populate on their schedules.
11. **autonomous_fixer false alarm**: UX check read stale v1 store
    `state/commitments_active.json` (zeroed since Jul 6) and flagged "0
    commitments" every cycle; real tracker (`data/commitments.json`) holds 9
    active. Pointed it at the real store → dry-run now "all clear".
12. **Healthchecks secrets**: compose used `${HC_SECRET_KEY:-changeme}` /
    `${HC_SUPERUSER_PASSWORD:-changeme}` defaults — rotated to random values in
    compose `.env`, recreated container, rotated the DB admin password.

## Verified green
- scheduler single daemon (systemd), consolidated_health + 16 core jobs success
  in recent window; 0 failed systemd units; disk 37%; 21Gi RAM free.
- scheduler state prunes stale keys; healthchecks pings 200 in logs.

## Notes / gotchas
- SSH display mangles `hc_ping.sh` → `ln` etc. Use `od -c`/`cat -A` to verify
  bytes. Heredocs over ssh corrupt → write file then `scp`/`python3 file.py`.
- Healthchecks API: `/ping/{uuid}` = success, `/ping/{uuid}/start`, `/ping/{uuid}/fail`
  only — there is NO `/success` route (returns 404). hc_ping.sh maps success→bare.
- Healthchecks SITE_ROOT requires `Host: healthchecks.home` header on every ping.
- State file is authoritative over scheduler.log for job status.
- Remaining backlog: 117 stale agentharness infra tests; 7 healthchecks checks
  not yet wired to jobs that don't exist (db-backup/backup-volumes/verify-backups/
  cve-scan/docker-ghost-check — jobs removed); ARCHITECTURE/README docs still
  reference old fixer behavior.
- Pushed: home repo commits 574dacf (repair stack), 0b856c9 (scheduler pings +
  prune), a9d2eee (UUID wiring). agentharness: e36396b (consolidated_health),
  16cb1d0 (fixer store fix).
