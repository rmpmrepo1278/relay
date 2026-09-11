# Relay — backup watchdog nag fix (2026-09-10 ~16:40Z)

## What the user saw
Repeated Telegram spam: "🛠 Auto-fixed by systemd_fix_watchdog: container docker-socat down -> restart rc=1, No such container" + "backup report status=warning aged 10.8h/16.6h/22.7h".

## Root cause (2 real defects through aliased bash)
1. systemd_fix_watchdog.py CRITICAL still listed ghost container `docker-socat` (replaced ~Sept by the method-restricted Docker API proxy). Every 2-min cycle tried restart -> rc=1 "No such container: docker-socat" -> Telegram re-alert forever; a ghost can never be restarted.
2. backup_all_report.json was stale (mtime 02:19Z, status=warning from a transient OneDrive "failed to get root drives/1C010EBCC25B417C" hiccup) and the <=26h age+warning gate re-nagged each cycle.

## Verified healthy (not the failure)
- docker-socat: 0 reference left in watchdog (grep -c = 0), py_compile OK.
- msonedrive: token valid (expires 2026-09-10T17:28), rclone lsd rc=0.
- Fresh manual push: rclone copy full_20260910_020225 -> msonedrive:HermesBackups/... = rc=0, 147.8 MiB, 9/9, listed after.
- Fresh report regen via disaster_recovery.py: status=success, onedrive_push ok, report_age_h 0.0.

## State
- Hermes health/watchdog clean. If same signature reappears -> config drift again, not real fault.
