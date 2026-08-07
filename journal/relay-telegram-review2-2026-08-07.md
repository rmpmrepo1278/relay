# Relay Journal — 2026-08-07 — Telegram Exchange Review #2 (auto-fix honesty bug)

## Context

Reviewed the second Telegram exchange (Aug 04–06). Recurring noise: doctor
"collaborator-memory 0 nodes", CoS briefing ":18090", and repeated "MenteDB is
DOWN" plus an auto-fix that claimed success but was unverified.

## Status of each issue

### 1. MenteDB DOWN — RESOLVED (previous session), verified again
- Container is `mentedb:fixed` (my rebuilt image), **Up 4h+**, RestartCount 0,
  healthy at `http://localhost:6677/v1/health`.
- The auto-fix session at 17:30 PDT Aug 06 ran BEFORE the fixed container
  existed; its "DOWN" alerts were accurate at the time.

### 2. Auto-fix false success — FIXED (this session)
`auto_fix_delegate.py` had two honesty bugs:
- `post_fix_health_check("service_down")` ran a bare `docker ps | head -20` and
  declared PASS on exit code 0 — it passed even when the target container was
  still down (how it reported "Health: ✅ PASS" while mentedb was down).
- `spawn_claude` returned `status:"completed"` whenever Claude exited 0, even
  with an **empty result** (0 tokens, 382ms — nothing performed).

Fix (commit `3eea727`, pushed):
- Health check now extracts the container name from the issue
  (`_extract_container_name`) and runs
  `docker ps --filter name=^/<name>$` — PASS requires the container to be Up
  and not Restarting.
- Empty/no-op delegate results are marked `failed` ("no action performed"),
  never `completed`.
- The critic (`autonomous_fixer.verify_fix`) was already working — it sent the
  correct "⚠️ Fix unverified" message. The delegate's premature PASS was the bug.

### 3. Doctor "collaborator-memory (0 nodes)" — resolved (previous session)
- Removed the markdown-only repo from CRG watch; `crg_graph_health` returns `[]`.
- All occurrences in this exchange were from Aug 04–05, before the fix.

### 4. CoS briefing ":18090 / Calendar unavailable" — resolved upstream
- Commit `7eda9a7b3` (Aug 06 11:00) already switched LLM check to :8080 and
  calendar to the `calendar_intelligence.py` cache. All briefings in this
  exchange predate the fix. Verified current `cos_briefing.py` uses :8080.

### 5. Duplicate / test messages — mitigated
- "DRYRUN dedup test", duplicate CoS briefings, repeated DOWN alerts all
  predate the bridge dedup deployment. Dedup cache is active
  (`~/.hermes/data/telegram_dedup.json`, 35 entries).

## Follow-ups (not done)
- Email digests arrive repeatedly (4/5/7/11 new in 24h) — possible UX spam;
  consider throttling/collapsing digests. Product decision, not a bug.
- Tailscale daemon restart on Mac pending user action (CLI 1.102.2 vs daemon
  1.94.1 mismatch). Command: `sudo launchctl kickstart -k system/homebrew.mxcl.tailscale`.
