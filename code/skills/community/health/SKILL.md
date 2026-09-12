---
name: system_health
description: Auto-healing homelab guardian
author: hermes-local
tags: [system, maintenance]
---
# System Health Skill

**Purpose:** Keep services running smoothly.

**Checks:**
- Disk space (prune at 85%, emergency at 92%)
- Scheduler daemon health
- Telegram bot conflicts (409 errors)
- Container health
- Stale lock cleanup

**Actions:**
- Auto-restart failed services
- Docker image prune
- Log rotation
- Alert on issues via Telegram
