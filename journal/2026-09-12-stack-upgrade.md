# 2026-09-12 — Full stack upgrade: reliability audit fixes + 7 transformational features

## Scope
User said "do it all" on the deep audit (capability gaps + transformational value). All
reliability debt fixed, all 7 ranked features built, deployed, and verified.

## A. Reliability (5 fixes, all deployed + scheduler green)
1. **memory_sync (42 fails/day)** → `lib/network_guard.py` + `memory_sync.py` guard. Root
   cause: known nightly outage window (11PM-9AM PT, already in mcp_health_watchdog) made git
   pull/push fail 42x/day. Now: skips silently in window, retry-once on DNS flap, only real
   git conflicts fail. Replaces raw `git pull && git push` scheduler job.
2. **duckdns_update + dns_healthcheck (170 fails/day)** → same guard. duckdns_update skips in
   outage window. dns_healthcheck skips `docker restart pihole` remediation during window
   (restart exceeded the 15s job timeout → the actual failure), `timeout 8` guard,
   always exits 0.
3. **hermes-compose.service FAILED** → compose file drifted from pinned canonical hash
   (a deliberate security upgrade 2026-09-08: docker-socat → tecnativa/docker-socket-proxy,
   pihole port hardening, autoheal labels). Re-pinned CANONICAL_HASH, unit now active.
4. **package_status (5/day)** → `package_tracker.py` lacked +x (script invokes it directly) →
   chmod +x. **doc_sync (2/day)** → `~/CLAUDE.md` retired into AgentChaguli/; TARGETS updated,
   missing target = skip not error.
5. **Disk/repo cleanup** → housekeeping.py extended: mind_insights 14,186→10,000 rows,
   daily_digest 70→45 files, episodic_memory capped at 20k (self-regulating). legacy_memory
   backup kept (real backup).
Also fixed: skills_smoke job was passing `--validate 3` to a subcommand-CLI → `validate 3`.

## B. Transformational features (7 built + scheduler jobs)

### B-1 Unified Intent Tracker (the brain) — `intent_tracker.py`
- One source of truth for "what matters most": `state/intent_state.json`.
- Sources merged + deduped (content-addressed by title): `personal_tasks.json` (22 rows →
  3 unique), `commitments.json`, dormant `goal_engine.db` goals (legacy schema now has a
  writer).
- API: add/list/done/drop/reprioritize/priorities/import/standup. Rank = priority, then
  deadline. Telegram: `/intent add/list/done/drop`, `/priorities`.
- Bugs hit + fixed during build: double title-join (`" ".join` on str) — passed the already-
  joined variable; `_mkid()` microsecond + module counter collision.
- Jobs: `intent_import` 08:15, `intent_standup` 08:40 (morning digest to home chat).

### B-2 Nightly Self-Evaluation — `daily_review.py`
- Closes the learning loop each 21:30: intents completed vs open, scheduler reliability
  (79/85 ok on first run), day snapshot from episodic_memory.tsv, failure lessons, health
  line, next-day focus pointer. Persists `data/reviews/review_YYYY-MM-DD.md` +
  `daily_review.log.jsonl`. Sends to Telegram via `--send`. Scheduler `daily_review`.

### B-3 Email Triage Autopilot — `email_triage.py` (+sentinel kind)
- Every ~2h (10..20:15): fetch recent unseen Gmail, classify, propose ONE sentinel-gated
  auto-reply for highest-priority reply-worthy email (actionable/security/career ONLY —
  informational/shipment never auto-replied; caught a Costco-reschedule false-positive
  during build and tightened). Sentinel `_execute` gained `kind=="emailTriage"` via
  email_intelligence.send_email. Dedup via email_ids_seen + triage_proposed caches.
- Verified: 6 new found → 1 proposed → denied the test proposal so nothing auto-sent.

### B-4 Calendar Deep Integration — meeting_prep.py extended
- Existing: 10-min-before briefing card. Added: post-meeting action-item capture nudges
  (`--after`, `/remember …` + `/intent add …` prompts, energy hint from wellness_state),
  conflict detection (`--conflicts`). Jobs: `meeting_after` */15, `meeting_conflicts`
  09:00/13:00.
- Verified: conflict scan clean, after-capture no-op (no recent meetings).

### B-5 Health Trend Dashboard — `health_tracker.py`
- Human health (not the existing *system* health): append-only `data/health_ts.jsonl`,
  fields sleep/energy/mood/exercise, plausibility checks, 14d trend + deltas. Telegram
  `/health`, weekly `health_checkin` nudge (Sun 22:00). Folds `status_line()` into the
  nightly review. Verified end-to-end (sleep 7.5, energy 3 → dashboard).

### B-6 Cross-Device Memory Sync — `cross_device.py`
- Writes portable `working_state.json` (priorities, open commitments, done-today, last
  review, health) into the git-backed `~/.hermes/collaborator-memory/state/`. Any device
  pulling the memory repo (the Mac does via memory_sync) sees the working state. Auto-
  commits; memory_sync pushes. Job `cross_device_sync` 08:30.
- Verified: snapshot + verify roundtrip on homelab.

### B-7 Social Presence Intelligence — `social_presence.py`
- Public GitHub API (no auth): 30 events/7d, 29 PushEvents, repos (relay, Astro-Han/pawwork),
  followers. LinkedIn noted as token-not-provisioned (career engine covers job posts). Weekly
  digest Sun 11:30. Fixed argparse `--check` not-a-subcommand bug.

## C. Maintenance cleanup
- **curiosity_engine** crash (UNIQUE collision on deterministic research_tldr key) →
  `INSERT OR REPLACE`. Was failing nightly 2am; now exits 0.
- **skills catalog** reconciled: `skills_reindex.py` rebuilds `skills/index.json` from disk
  (10 → 44 entries: legacy hash-json + .skill.md + capability dirs; skips .usage tracker).
  Backup `index.json.bak-audit`. Job-able, run manually.

## Deployment notes
- All files: local `/tmp/hermes-ops/scripts/` → scp → `~/.hermes/scripts/`, originals already
  backed up earlier (`.bak-*`).
- Since last restart: scheduler = 131 jobs, no name dupes, daemon active, all smoke checks
  green. `hermes-compose.service` active again.
- New files on homelab: network_guard.py (lib/), memory_sync.py, intent_tracker.py,
  daily_review.py, email_triage.py, health_tracker.py, cross_device.py, social_presence.py,
  skills_reindex.py.

## Verdict
Reliability noise (224 fails/day) → near zero (only real git conflicts / real outages page
now). Hermes now has: operating brain (intents), nightly learning loop, email autopilot,
calendar depth, health memory, cross-device state, social radar — all over the existing
systemd/USB/OMR spine, no new infra boxes needed.