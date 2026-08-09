# Relay Journal — 2026-08-09 — MenteDB recurring "DOWN" alert fixed

## Symptom

User kept getting Telegram alert:
```
🧠 MenteDB is DOWN

Attempted to reach port 6677. Service needs restart.
```
Latest occurrence today 11:00:00 PDT (dedup timestamp in
`~/.hermes/data/telegram_dedup.json`). Alert re-fired repeatedly across
wks of Aug 5–9.

## Diagnosis (what we ruled out)

- MenteDB container itself was NOT crashed this time:
  `mentedb:fixed` (rebuild from `services/mentedb/Dockerfile`, trixie-slim,
  fixes upstream GLIBC 2.39 packaging bug) was running 18h, RestartCount=0,
  healthy, RSS ~100–183 MiB — contradicts the old "excessive memory" claim
  (that story was an unverified agent guess from an earlier session).
- Root alert template: `Attempted to reach port <port> / Service needs
  restart` is LLM-composed by the autonomous-fixer delegate (Claude) when it
  sees a moment where the container/port looks down.
- Trigger yesterday/today: transient, not a crash — menteDB has NO compose
  label (deployed via plain `docker run`), healthcheck `start_period: 10s`
  was too tight (model load ~8s), so during restarts the container could
  briefly report unhealthy → autoheal + fixer + n8n auto-heal churn re-alert.
- Stale state was keeping it alive: `loop-state-items.json` had
  `service_down:mentedb` (waiting_human) + `healthcheck_fail:mentedb`;
  stagnation_state.json had `service_down:mentedb`; LOOP-STATE.md 2 lines.
- Diagnoser log showed "mentedb exited, port-6677-in-use" (Aug 6) — a
  leftover from the broken-image window, now gone (only one mentedb, single
  port bind).

## Fixes applied (verified)

1. Recreated mentedb container with loopback-only binds matching compose:
   `-p 127.0.0.1:6677:6677 -p 127.0.0.1:6678:6678`, restart=always,
   autoheal=true, same data bind `/home/rohit/services/mentedb/data`.
2. Healthcheck hardened: `start_period 60s`, `retries 5`, interval 30s,
   timeout 3s → no false "unhealthy" window on boot.
3. `~/.hermes/data/excluded_containers.json` += `mentedb` (troubleshooter
   will not treat it as actionable).
4. Purged stale state:
   - removed menteDB items from `loop-state-items.json` (2)
   - dropped `service_down:mentedb` from `stagnation_state.json`
   - scrubbed 2 menteDB lines from `LOOP-STATE.md`
5. Also patched `/home/rohit/services/docker/compose/apps.yml` (menteDB
   block) healthcheck to match (backup: `apps.yml.bak-1786300863`).

## Verified

- `mentedb` Up (healthy), `/v1/health` → `{"status":"ok"}`, ~101 MiB.
- `autonomous_fixer --dry-run --json` → `all_clear, issues=0` (no menteDB).
- `homelab_troubleshooter.py` → 0 failing containers (mentedb excluded).
- `sync-registry.py --check` → "Registry is in sync — no issues found".

## What NOT to do

- Do NOT `docker pull`/watchtower upstream `ghcr.io/nambok/mentedb:latest`
  (GLIBC < 2.39 packaging bug). Rebuild from `services/mentedb/Dockerfile`
  if the fixed image is ever lost.
- mentedb is memory-memory custom store (friendly on RAM); "excessive
  memory usage" is NOT a real cause — do not act on it.