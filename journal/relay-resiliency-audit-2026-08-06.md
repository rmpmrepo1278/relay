# Relay Journal — 2026-08-06

## Resiliency & Backup Stability Audit

Follow-up to the all-systems check. User asked whether any stability/resiliency
gaps remain. Audited backup coverage, restart policies, memory, and offsite
redundancy.

### Findings
- **All 13 services active, 0 failed.** Docker 35/35 containers have restart
  policies. Watchtower `--label-enable` but 0 containers labeled (updates
  nothing; stability-safe). Traefik healthy (301 on :80), no healthcheck.
- **Scheduler memory leak fixed** earlier: 4.5G RSS (peak 13.5G) -> 10.1M after
  restart; all recent jobs SUCCESS.

### Backup audit — initial alarms, corrected
Initially looked like kopia was "broken" (repo not connected, snapshots stale).
Root-cause investigation showed that was a **misread of legacy logs**:

1. **Dead `homelab-backup.service`+timer (user/systemd)** still exec'd the OLD
   `agentharness/scripts/kopia_backup.sh`, which ran kopia as non-root against
   an **unconnected** repo (invalid `--exclude-dir` + `prune` flags). It failed
   nightly. Fully superseded by scheduler `backup_all` -> `backup_all.py`.
   **-> Disabled service + timer.**
2. **Offsite GDrive backup ~2 months stale.** `cloud_sync` job ran
   `sync_backup_remote.sh`, which synced `/mnt/usb/backups/docker-volumes`
   tarballs that stopped being generated **Jun 15** (kopia had taken over
   volumes). GDrive only had data to Jun 15.
   **-> Repointed script to sync fresh `db-dumps/`. Verified upload works**
   (63.8 MiB, GDrive Used 898->962 MiB). Committed `ccfd538` + pushed.
3. **Kopia maintenance overdue (1092 index blobs)** — last run Jul 9. Also found
   maintenance owner (`rohit@home-hp`) mismatched the repo config username
   (`root`), since `backup_all.py` ran kopia via sudo. Fixed the ownership to
   `root@home-hp`, chown'd 7849 root-owned repo files to the right context, ran
   full maintenance: **reclaimed ~10.3 GB** via GC, compacted epoch indexes,
   cleaned logs. Restored `backup_all.py` to sudo-based (root-only dirs need it).
   Reports 3/3 OK; no new root-owned file leak.
4. **linkwarden** container down, DB dump skipped — it is defined in
   `apps.yml` but never launched in the active stack (paperless, healthchecks,
   immich, n8n, searxng, vaultwarden all up). Intentional/not-deployed, no action.

### Net effect
- Config + volume + DB backups: **working** (kopia sudo + db-dumps).
- Offsite redundancy: **restored** and current as of today.
- Repo health: maintenance healthy, ~10.3 GB reclaimed.

Commit: AgentHarness `ccfd538`.