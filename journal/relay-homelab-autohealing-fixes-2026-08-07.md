# Relay — Homelab self-healing fixes (2026-08-07)

## Context
Health audit found 4 self-healing gaps that the automation layer did NOT catch:
silent/long failures that needed a human click.

## Fixes
1. **homelab_research_pipeline.py** — restored from git `aad0b78^` (removed Aug 4
   as "dead-code", but the systemd unit depended on it — same false-negative
   class as the syslog_emit gap). Verified: runs, 20 items assessed, results
   written to pipeline_results.jsonl, Telegram notified.

2. **homelab-backup.timer** — disabled Aug 6, re-armed.
   Kopia user script `kopia_backup.sh` pointed at empty `~/.config/kopia/
   repository.config` ("repository is not connected"). Switched to the root
   repo config via passwordless sudo (root-maintained repo at /mnt/usb/kopia-
   repo-volumes). Fixed invalid kopia 0.23 flags (`--exclude-dir`, `snapshot
   prune`). Now uses `policy set --add-ignore=venv/.cache/__pycache__` and
   tags in `kind:value` form. Compose/hermes/agentharness snapshots verified.

3. **Root `/usr/local/bin/kopia-volume-backup.sh`** — failed "kopia: command not
   found": root cron PATH lacks `/usr/local/bin`. Added `export PATH` plus
   absolute `/usr/local/bin/kopia`. Syntax + repo status verified OK.

4. **new `systemd_missing_guard.py`** — ExecStartPre guard that detects a missing
   ExecStart file, alerts via Telegram, and fails the service start instead of
   a silent restart loop. Installed as drop-in on 7 script services:
   homelab-research, homelab-backup, system-health-check, hermes-scheduler,
   hermes-mind-loop, hermes-upgrade, n8n-bridge.

## Verified
- Pipeline: 20 items, exit clean.
- Kopia: snapshots created for compose/hermes/agentharness; maintenance GC ran.
- Backup service: "Finished", 4.7s, 406MiB peak.
- Guards: system-health-check + research run ExecStartPre status=0/SUCCESS.
- All timers active: homelab-backup, homelab-research, system-health-check.

## Notes
- Restored pipeline file is staged (`A`) in git, uncommitted.
- `systemd_missing_guard.py`, `kopia_backup.sh`, drop-in confs are new files.
- homepage kopia path missing (non-critical, `|| continued`).
- Kopia blob count high (~1180) — schedule periodic `maintenance run --full`.
- Deeper job: audit dead-code scan should include systemd unit ExecStart refs.
MDEOF
cat /tmp/journal.md | ssh homelab-cmd 'cat > ~/.hermes/collaborator-memory/journal/relay-homelab-autohealing-fixes-2026-08-07.md && echo "journal written" && ls -la ~/.hermes/collaborator-memory/journal/ | grep autohealing'