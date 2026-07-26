# Hermes State Summary — Jul 18 2026 (Final)

## Running Processes
| Process | PID |
|---------|-----|
| hermes_scheduler.py --daemon (84 jobs) | 1293144 |
| telegram_bot.py | 1567272 |
| agentharness-inbox-watcher.service | running |
| agentharness-dashboard.service | running |

## Calendar Auth
- ✅ Token saved with refresh_token
- ✅ calendar_cache (2h) + calendar_reminder (15min) jobs active
- ✅ Morning briefings include calendar context

## Cleanup Done Today
- Removed: rotated logs >1M (4 files, ~6M freed)
- Removed: WAL file (134M freed)
- Archived: 5 unused scripts to archive/scripts_20260718/
- Vacuumed: state.db

## Disk Usage
- Root: 59G / 221G (28% used)
- Logs: 9.8M
- State DB: 133M

## Next Auto Tasks
- system_doctor: every 30min (disk cleanup)
- calendar_cache: every 2h
- capability_tracker: every 2h (data collection)
