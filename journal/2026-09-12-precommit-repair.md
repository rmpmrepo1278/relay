# Pre-commit hook repair: ollama decommission + Telegram bridge 404 fix

Date: 2026-09-12

## Problem
Commits in the `/home/rohit` monorepo were blocked by its strict pre-commit hook:
1. **Stale `ollama` critical-container check"** — ollama was decommissioned (compose no
   longer defines it; only stale comments/env refs remain), but the hook hardcoded
   `hermes ollama healthchecks` and `regression_test.py` required the container →
   permanent FAIL.
2. **`tg-send` false FAIL"** — the regression suite's Telegram-send test harness
   returned FAIL `?` for throttled sends (bridge returns `{"status":"ok","throttled":true}`
   with no `response` payload). This **masked a real outage**: the running `n8n-bridge`
   container could not actually send Telegram at all.

## Root cause of the real 404
The `n8n-bridge` Docker container (hermes-agent image, network_mode: host) runs with
`HOME=/opt/data` = the mount root of `~/.hermes` (compose sets `HERMES_HOME=/opt/data`).
`n8n_bridge_server.py` ignored that env and computed every path as
`Path.home()/".hermes"/...` = `/opt/data/.hermes/...` (nonexistent). So the container
bridge loaded no `~/.hermes/.env`, had no `TELEGRAM_BOT_TOKEN`, and every real send
returned `HTTP Error 404` — hidden because throttle short-circuits the send path first.
The script lived twice (image copy `/opt/hermes/.hermes/scripts/` and the mounted
`/opt/data/scripts/` = tracked relay `code/scripts/`); the mounted copy is authoritative.

## Fixes (all committed + pushed)
- **`code/scripts/n8n_bridge_server.py`** (relay commit `0e3de1b`): define
  `HERMES_HOME = Path(os.path.expanduser(os.environ.get("HERMES_HOME") or "~/.hermes"))`
  and derive all paths (THROTTLE_FILE, HEAL_STATE_FILE, SCRIPTS_DIR, _ENV_PATH,
  PROPOSAL_DIR, dedup, state, `_HH`, inner `HERMES`/`HERMES_HOME`) from it.
  Host/systemd deployment unchanged (env unset → `~/.hermes`); container now resolves
  `/opt/data/.env` correctly. Verified: real send `ok:true message_id:9919`, container
  restarted + healthy.
- **`code/scripts/regression_test.py`** (same commit): drop `ollama` from
  critical-container set → `{hermes, healthchecks}`; replace `test_ollama` with
  `test_autoheal` (verifies the autoheal watcher is live); `_send_tg` returns full
  payload so throttled sends are treated as PASS (bridge accepted the message).
- **`/home/rohit/.git/hooks/pre-commit`**: critical list `hermes ollama healthchecks`
  → `hermes healthchecks` (backup `pre-commit.bak-20260912`).
- **Rebuilt inventory**: `/home/rohit/AgentChaguli/services/bin/inventory.py` wrote
  `inventory.json/md` + `n8n/registry.json` — 32 services (was 43). Drops: decommissioned
  `compose:ollama`, `compose:openwebui`, whole `agentharness:*` project (9 entries; the
  project/compose file no longer exists anywhere, no containers), plus dead systemd units
  (`crg-daemon`, `dashboard`, `n8n-bridge`, `webhook-receiver`). Adds 5 live units
  (`chatllm-lfm`, `chatllm-qwen-a3b`, `dsh-web`, `magnitude`, `proxy-watchdog`).
  Regeneration was manual (no timer exists despite `system_health_check.py` docstring
  implying `inventory.timer` regenerates every 5 min — latent gap, noted).
- **Cron**: removed stale `30 12 * * * ollama-cleanup.sh` entry; script preserved at
  `/home/rohit/scripts/.ollama-cleanup.sh.removed-20260912`.

## Verification
- Relay `regression_test.py`: **ALL PASSED (7/7)**: bridge-ping, tg-send (real
  `msg_id=9920`), docker-ps (27 containers), autoheal, inventory (32 services),
  ask-func, gdrive-owned.
- `/home/rohit` commit `650a95cdb5` (inventory regen, +93/−396) passed the **full**
  pre-commit hook — no `--no-verify`. CRG incremental analysis, bridge/docker/critical/
  inventory checks all PASS.
- CRG graph auto-rebuild after relay push (329 files, 2837 nodes, 33744 edges).
- n8n-bridge container restarted → healthy, `/ping` → pong:true.

## Notes / latent gaps
- `inventory.py` silently skips missing project files (no warning) — caused the
  9-entry agentharness disappearance to pass quietly. Consider adding a warning.
- No automated inventory regeneration (no `inventory.timer`/cron) — inventory is only
  regenerated manually or by the AgentChaguli pipeline. `system_health_check.py`
  docstring implies a timer should exist.
- Relay repo `.git/hooks/pre-commit` (CRG-installed) still not executable — warning
  only, skips it. Post-commit hook IS executable and auto-rebuilds the graph.
- CRG `dead-code` reports ~30 symbols in n8n_bridge_server.py — all false positives
  (dynamically-registered `@handler` endpoints + thread targets).
- `git add` on tracked files under `services/inventory/` requires `-f` (gitignore
  `inventory/` pattern still matches; tracked files bypass it for updates but path
  listing refuses).