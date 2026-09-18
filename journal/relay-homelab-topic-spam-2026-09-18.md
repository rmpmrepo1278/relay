# Homelab topic (10026) spam — root-caused + fixed (Sep 18 2026)

Rohit asked: "what are all these messages in homelab topic? investigate the
genuine ones and noise and reduce the spam."

## Inventory of the messages seen on the topic

| Message | Source | Verdict |
|---|---|---|
| "⚠️ Backups are not configured (age=None…) / Please configure Kopia…" (3 variants) | `homelab_agent_autonomous.py` daemon `notify` — LLM (hop haiku-4.5) hallucinated prose from a FALSE `backups=not_configured` signal, rephrased each cycle | **NOISE (false)** — kopia was always healthy |
| "⚠️ infra update" | Same `notify`, code fallback at `homelab_agent_autonomous.py` (old `or "infra update"`) when LLM text empty | **NOISE** |
| "🔴 Homelab Health: CRITICAL — docker:error systemd:error disk:error …" | `homelab_agent.run_full_health_check()` auto-send, invoked INSIDE the bridge container where docker/systemctl/df can't see the host | **NOISE (false)** — host is healthy |
| "🏗️ Homelab — critical …" reply card | bridge `_agent_cmd("homelab")` formatting the same in-container result | **NOISE (false)** |
| "⚠️ Infrastructure updates: 3 updates (3 security)" | `notify` from the daemon — GENUINE at the time (Round-5 ran apt upgrade; fine, transition now over) | **genuine, one-shot** |
| "Hi" | user message routing | genuine |
| Cost report | `cost_dashboard.py` periodic report to 10026 | genuine, keep |

## Root causes found

1. **`_check_backups` ran plain `kopia` (user config)** → "not connected" →
   `not_configured` every cycle. The repo lives under ROOT's config
   (`/mnt/usb/kopia-repo-volumes`, jobs run via `sudo -n`). Fixed to
   `sudo -n kopia repository status` + `snapshot list` in BOTH
   `homelab_agent_autonomous.py` and `homelab_agent.py`.
2. **Kopia JSON parsing was doubly broken**: `kopia snapshot list --json`
   emits ONE pretty-printed JSON array (not one object per line), AND the code
   took `snapshots[-1]` (source-grouped, often OLDEST) instead of the newest
   `startTime`. Result: "1 snapshot, 36 days old" false alarm → now 760
   snapshots, age 9.4h, healthy. Added `_parse_json_stream()` (handles array +
   concatenated-object forms) and `max(... key=startTime)` in both files.
3. **Daemon `notify` was chosen by the LLM each cycle with no dedup** → LLM
   invented alert text from the false signal, rephrasing every 15 min. Fixed
   with a transition policy: `_notify_sig()` anchors an alert to the actual
   abnormal `(domain,status)`; `_notify_policy()` rejects empty content (kills
   "infra update"), rejects repeats within 6h, rejects alerts with no abnormal
   signal. Steady state is silent; a genuine transition still alerts.
4. **Health card auto-sent on every non-healthy check** in
   `run_full_health_check()` → spam from in-container probes. Removed the
   auto-send; callers decide (daemon transitions / bridge reply).
5. **In-container probes fabricated failures**: `docker`/`systemctl`/`df`/
   `free`/`curl`/`apt` missing or host-scoped in the bridge container →
   fabricated `error`/`critical`. All probes now return `n/a` when the tool or
   the mount doesn't exist in this environment; `n/a` is skipped in the overall
   status (never drags into critical). `check_agentbus` treats host-loopback
   connection-refused in-container as `n/a`.
6. **Bridge `_agent_cmd("homelab")` now answers from the HOST daemon's fresh
   cache** (`state/homelab_state.json` `last_signals`, ≤25 min old) via new
   `_homelab_cached_signals()` — truthful host state, no in-container checks.
   Falls back to the (now env-aware) live check when stale.
7. **~5-min churn "Verifying Kopia backups" in `homelab_agent.log`** — traced
   with a stack-trace probe: `mind_loop.py --daemon --interval 5` →
   `dispatch_plan → agent_orchestrator.dispatch → homelab_agent(task)` →
   `homelab_agent.py:602` ran `verify_backups()` unconditionally on backup-keyword
   tasks. So a full kopia `repository verify` (as non-root, failing silently)
   ran every ~2-5 minutes, around the clock. Fixed: `verify_backups()` is
   **file-persisted self-throttled to once per 6h** (`state/homelab_verify_lock.json`),
   because a module-level dict resets per process and several callers exist
   (mind_loop 5-min, homelab daemon 15-min LLM path, bridge replies). All now
   share the 6h window. Runs via `sudo -n kopia repository verify`.

## Verified

- Daemon manual cycle: `backups: healthy (age 9.5h, 760 snaps)`, plans
  `[nothing / all healthy]` with LLM, 0 errors, **no notify sent**.
- `_notify_policy`: identical repeat → rejected (6h window); healthy → rejected;
  genuine error transition → allowed once.
- `run_full_health_check` on HOST: all 7 checks healthy, overall healthy
  (previously critical/stale from parse bug + grep rc).
- `check_updates` false-error fixed (`grep` rc=1 on empty → `|| true` → current).
- `_homelab_cached_signals()` → overall healthy, reads daemon host state.
- `verify_backups()` → skipped_throttled within 6h window.
- Regression **7/7 PASS**; daemon + `hermes-mind-loop` + `n8n-bridge` restarted
  (both containers + services active).

## Files changed (backups: *.bak-20260918-121551)

- `homelab_agent_autonomous.py` — sudo kopia backups/verify, notify transition
  policy (`_notify_sig`/`_notify_policy`), `verify_backups` cooldown 360m,
  `NOTIFY_MIN_INTERVAL 6h`, no-content notify skip, per-domain status tracking
  in reflect, kopia JSON stream parser + newest-snapshot selection.
- `homelab_agent.py` — `verify_backups` self-throttle + sudo; kopia stream
  parser + newest-snapshot; `check_updates` grep fix; env-aware probes
  (docker/systemd/disk/memory/agentbus → `n/a`); auto-send card removed;
  `n/a` neutral in overall.
- `n8n_bridge_server.py` — `_homelab_cached_signals()` + `_agent_cmd("homelab")`
  prefers host daemon cache (fallback to live env-aware check).

## Notes

- `mind_loop` dispatches a homelab check task every 5 min by design (its health
  check capability) — that is fine now: health check + auto_heal only act on
  real signals; the pathological part (unconditional kopia verify) is throttled.
- `cost_dashboard.py` periodic cost report to 10026 is genuine and kept.
- Same latent class checked elsewhere: `homelab_reporter.py` (daily digest) and
  the daemon's `updates`/`apply_updates` paths already carry their own gates.