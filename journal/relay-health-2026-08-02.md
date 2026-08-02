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
13. **proactive_orchestrator consecutive_failures=5** (real gap): curious_explorer
    crashed with JSONDecodeError every cycle. Root cause: SEEN_FILE
    (`state/curious_seen.json`) corrupted by non-atomic writes — curious_explorer
    is invoked BOTH by the scheduler (daily 8:30) AND by proactive_orchestrator
    (every 4h); overlapping writes interleaved. Fixed: atomic save (tempfile +
    os.replace) + resilient load (extract strings, quarantine as `.corrupt`).
    Verified: curious_explorer exit 0, orchestrator consecutive_failures → 0.

## Phase 2 — proactive decision engine + capsule verification + decision ledger

Built the three capability pillars (all new in `~/.hermes/scripts/`, pushed home
repo `1ea2eba`, agentharness `b75abc1`):

- **proactive_engine.py** (new): state-change-TRIGGERED engine (closes the core
  proactivity gap — previously every module ran on fixed schedules only). Watches
  7 signal files (health_dashboard.json, scheduler_state.json, task_queue.json,
  interest_profile.json, insights.json, capsules/outcomes.jsonl,
  curious_explorer_results.json) via content hashes; on change, scores 5
  candidate actions (troubleshoot / scheduler_repair / capsule_learn / curiosity /
  insight_surface) with urgency + cooldown; fires via subprocess then records in
  ledger. Baseline snapshot at `state/proactive_engine_snapshot.json`.
  Registered in scheduler: every minute, timeout 320. First scheduled run
  verified success (returncode 0, 0.04s — no-op while signals stable).
- **decision_ledger.py** (new): append-only JSONL `data/decision_ledger.jsonl`;
  record/resolve/stats/recent. Wired into all three action sinks:
  `hermes_mind.py` (actor hermes_mind, action fix_<target>),
  `mind_loop.py` execute_plan (send_telegram + run_command branches),
  `autonomous_fixer.py` (actor autonomous_fixer, triggered_by detected_issue).
  Now live: mind_loop logs every plan action every cycle.
- **capsule_verify.py** (new): 15-min driver verifying capsule records from last
  24h older than 10min, appends verified:true + actual_outcome (via
  check_target_health docker probe). Registered in scheduler every 15min.
- **capsule_tracker.py** (canonical): added verify subcommand + get_stats
  verified-rate + check_target_health. 162 existing records (160 autonomous_fixer,
  91% fail) — verification will surface whether fixes actually helped.
- **feedback_loop.py** (restored): was missing from ~/.hermes/scripts/ entirely;
  restored from archive + adapter functions appended (record_action /
  load_feedback / check_action_outcomes) bridging into the decision ledger.

## Real bugs found via the ledger (second session)
- **mind_loop crash every cycle**: `from commitment_tracker import ... format_report`
  — function doesn't exist (commitment_tracker has get_status/check_overdue/
  get_upcoming only) → ImportError in cycle #1931's commitment check. Removed the
  dead import → cycle #1932 clean.
- **mind_loop backup verification was a guaranteed-fail no-op**: plan ran
  `kopia snapshot list --json` as user rohit, but the kopia repo lives under
  /root/.config/kopia (root-owned, `sudo kopia` required). Every verify_backups
  action returned error. Fixed to `sudo kopia snapshot list --json`; verified
  exit 0 → ledger shows outcome=success at 01:27:41. (Kopia itself healthy:
  backup_all success daily 02:00, kopia_dirs/volumes OK.)

## Verified green
- scheduler single daemon (systemd), consolidated_health + 16 core jobs success
  in recent window; 0 failed systemd units; disk 37%; 21Gi RAM free.
- scheduler state prunes stale keys; healthchecks pings 200 in logs.
- proactive_engine running on schedule (success, no-op on stable signals);
  capsule_verify runs (0 candidates until capsules settle).

## Notes / gotchas
- SSH display mangles `hc_ping.sh` → `ln` etc. Use `od -c`/`cat -A` to verify
  bytes. Heredocs over ssh corrupt → write file then `scp`/`python3 file.py`.
- Healthchecks API: `/ping/{uuid}` = success, `/ping/{uuid}/start`, `/ping/{uuid}/fail`
  only — there is NO `/success` route (returns 404). hc_ping.sh maps success→bare.
- Healthchecks SITE_ROOT requires `Host: healthchecks.home` header on every ping.
- State file is authoritative over scheduler.log for job status.
- Kopia repo lives in /root/.config/kopia → any non-sudo `kopia` command as rohit
  says "repository is not connected"; use `sudo kopia` (as backup_all.py does).
- Remaining backlog: 117 stale agentharness infra tests; 7 healthchecks checks
  not yet wired to jobs that don't exist (db-backup/backup-volumes/verify-backups/
  cve-scan/docker-ghost-check — jobs removed); ARCHITECTURE/README docs still
  reference old fixer behavior; proactive_engine candidate-action targets
  (troubleshoot/scheduler_repair) not yet observed firing end-to-end.
- Pushed: home repo 574dacf, 0b856c9, a9d2eee, f417301, 1ea2eba. agentharness:
  e36396b, 16cb1d0, b75abc1.
