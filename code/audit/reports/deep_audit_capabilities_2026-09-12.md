# Deep Audit — All Capabilities in Homelab + Agent Setup
**Date:** 2026-09-12
**Auditor:** Claude Code (auto-audit session)
**Scope:** All capabilities defined in `.hermes/HERMES.md` + supporting infrastructure
**Methodology:** Live system checks, code-review-graph analysis, config review, log inspection

---

## Executive Summary

The homelab + agent system is **operational with 27 containers all healthy**. The system covers 6 primary capability domains per `HERMES.md`. Several findings emerged:

- **Risk Score:** 0.35 (low) per code-review-graph
- **Key Test Gap:** `define_jobs` in `hermes_scheduler.py` has zero test coverage
- **Health Check Script:** Exists at `/home/rohit/scripts/healthcheck.sh` and `/home/rohit/.hermes/scripts/healthcheck.sh` (duplicated)
- **MCP Config:** Only `code-review-graph` registered in `.mcp.json`; 12+ MCP servers running via Docker but not all individually configured in `.mcp.json`
- **Telegram:** ✅ Reachable (HTTP 200)
- **OneDrive Backup:** ❌ Failed (2026-09-12 02:20)

---

## Capability-by-Capability Audit

### 1. Telegram (Primary Interaction Channel)

| Check | Result | Status |
|-------|--------|--------|
| Bot token present | ✅ `.hermes/.telegram_token` exists | ✅ |
| Bot reachable | HTTP 200 from `api.telegram.org` | ✅ |
| DuckDNS token | ✅ `.hermes/.duckdns_token` exists | ✅ |
| DuckDNS update job | `duckdns_update` runs every 5 min | ✅ |
| DNS healthcheck | `dns_healthcheck` runs every 5 min | ✅ |

**Findings:**
- ⚠️ Token files are world-readable (`-rw-rw----`) — should be 600
- ⚠️ `.duckdns_token` and `.telegram_token` are in `.gitignore` but accessible
- ✅ Telegram is the primary channel; daily briefs, meeting prep, and council votes all route through it

### 2. Bash Tools, MCP Tools, Script Execution

| Check | Result | Status |
|-------|--------|--------|
| MCP Servers registered | 1 in `.mcp.json` (code-review-graph) | ⚠️ |
| MCP Servers running | 12+ via Docker (homelab-mcp, code-review-graph, etc.) | ✅ |
| MCP Gateway | Port 8090 (homelab-mcp) | ✅ |
| Bash tools available | ✅ via hermes container | ✅ |
| `code-review-graph` MCP | 123,740 nodes, 1,087,987 edges | ✅ |
| `healthcheck.sh` | Exists at 2 locations | ⚠️ |
| `.hermes/.mcp.json` | Only code-review-graph configured | ⚠️ |

**Findings:**
- ⚠️ **MCP configuration drift:** `.mcp.json` only lists `code-review-graph`. The Docker containers run 12+ MCP servers (docker, homelab-ops, file, network, backup, git, calendar, rss, doctor, memory, codebase-memory, paperless) but they're NOT registered in `.mcp.json`. This means some MCP tools may not be discoverable through the standard interface.
- ⚠️ **Duplicate healthcheck.sh:** Exists at both `/home/rohit/scripts/healthcheck.sh` and `/home/rohit/.hermes/scripts/healthcheck.sh`. The `HERMES.md` GROUNDING RULE says to use `bash /opt/data/scripts/healthcheck.sh` but this path doesn't exist.
- ⚠️ **`agentharness` directory deleted:** Git status shows `D agentharness` — the AgentHarness framework (with code-review-bridge, data-management, global-chat-mcp, etc.) was deleted from the filesystem. Per `services/homelab/meta.yml`, these were "Decommissioned during Jul 5-6 2026 cleanup; compose declarations kept for reversal."

### 3. `/assess` — New Ideas/Tools Assessment

| Check | Result | Status |
|-------|--------|--------|
| `/assess` capability documented | ✅ in HERMES.md | ✅ |
| Assessment scripts | `adaptive_thresholds.py`, `capsule_verify.py` exist | ✅ |
| Council governance | 5-member council with voting | ✅ |
| Decision pipeline | `decision_council.py` runs every 4 hours | ✅ |

**Findings:**
- ✅ Assessment pipeline functional via council governance
- ⚠️ No dedicated `/assess` endpoint or command handler found — capability relies on council framework

### 4. Docker Auto-Deploy

| Check | Result | Status |
|-------|--------|--------|
| Docker Compose file | `/home/rohit/docker-compose.yml` | ✅ |
| Compose backups | 10 pre_deploy backups in `.hermes/backups/compose/` | ✅ |
| All containers healthy | 27/27 healthy | ✅ |
| Autoheal | Running, monitoring 14 MCP services | ✅ |
| Healthchecks service | Running (port 8004) | ✅ |
| Traefik reverse proxy | Running (ports 80/443) | ✅ |

**Findings:**
- ✅ Docker auto-deploy fully functional
- ✅ Pre-deploy backup system working
- ✅ Autoheal container monitoring all services
- ⚠️ `docker-compose` command not found (uses `docker compose` instead — expected for newer Docker)
- ⚠️ `apps.yml.bak-ollama-openwebui-2026-09-05` and `apps.yml.bak-audit-2026-0908` suggest recent decommissions

### 5. Homelab Pipeline (Discover, Evaluate, Deploy, Troubleshoot, Optimize, Report)

| Component | Status | Notes |
|-----------|--------|-------|
| **Discover** | ✅ `inventory.py` in `/home/rohit/services/inventory/` | `inventory.json`, `inventory.md` present |
| **Evaluate** | ✅ `decision_council.py` + `adaptive_thresholds.py` | 5-member council |
| **Deploy** | ✅ `docker-compose.yml` + pre-deploy backups | 27 containers |
| **Troubleshoot** | ✅ `systemd_fix_watchdog.py`, `mcp_health_watchdog.py` | Auto-fixes |
| **Optimize** | ✅ `core_patch.py` (weekly), `omniroute_mesh_probe.py` | Performance tuning |
| **Report** | ✅ `brief_feed.py`, `life_radiator.py`, `daily_report.md` | Daily/Weekly reports |

**Findings:**
- ✅ Pipeline fully operational
- ✅ `drift.json` and `self-heal.json` in inventory show drift detection
- ⚠️ `services/homelab/meta.yml` lists 12 declared-not-deployed services — these are decommissioned but compose declarations kept

### 6. 106 Scheduled Jobs via hermes-scheduler.service

| Check | Result | Status |
|-------|--------|--------|
| `hermes_scheduler.py` | 736 lines, `define_jobs()` returns job list | ✅ |
| Jobs defined | ~35+ active jobs in `define_jobs()` | ⚠️ |
| Cron entries | 13 crontab entries + personal_agent_scheduler.py | ⚠️ |
| Scheduler service | `systemctl status hermes-scheduler.service` → NOT FOUND | ❌ |
| `morning_pipeline.sh` | Present, runs daily | ✅ |
| `send_daily_digest.sh` | Present | ✅ |
| `session_debrief.sh` | Present | ✅ |

**Findings:**
- ❌ **CRITICAL: `hermes-scheduler.service` not found as systemd unit.** HERMES.md claims "106 scheduled jobs via hermes-scheduler.service" but the service doesn't exist as a systemd unit. Jobs are managed via: (1) `hermes_scheduler.py --daemon` mode, (2) crontab entries, (3) `personal_agent_scheduler.py`. The count discrepancy suggests the "106" may refer to total across all mechanisms.
- ⚠️ **`define_jobs` has zero test coverage** — code-review-graph identified this as the only test gap
- ⚠️ **Job count mismatch:** `define_jobs()` shows ~35+ explicit jobs, not 106. The discrepancy may be from: (a) cron entries outside the scheduler, (b) legacy cron scripts in `~/.hermes/cron/`, (c) `personal_agent_scheduler.py` jobs.
- ✅ Scheduler logs show Phase 1/2/3 completed successfully (Aug 23 audit)

---

## Infrastructure & Supporting Systems

### Monitoring Stack
| Component | Status | Port |
|-----------|--------|------|
| Grafana | ✅ Running | 3002 |
| Prometheus | ✅ Running | 9090 |
| Loki | ✅ Running | 3100 |
| cAdvisor | ✅ Running | 8082 |
| node-exporter | ✅ Running | 9100 |
| Alertmanager | ✅ Running | - |
| Uptime Kuma | ✅ Running | - |
| Netdata | ✅ Running | 19999 |

### Services Overview
| Service | Status | Port |
|---------|--------|------|
| Home Assistant | ✅ Healthy | - |
| Traefik | ✅ Healthy | 80/443 |
| Nginx Proxy Manager | ✅ Running | 81 |
| Homepage | ✅ Healthy | 3003 |
| Paperless | ✅ Healthy | 8000 |
| Immich | ✅ Healthy | 2283 |
| Bookstack | ✅ Healthy | 6875 |
| Linkwarden | ✅ Healthy | 3011 |
| Vaultwarden | ✅ Healthy | 8443 |
| Authentik | ✅ Healthy | 9001 |
| n8n | ✅ Healthy | 5678 |
| SearXNG | ✅ Healthy | 8118 |
| Healthchecks | ✅ Healthy | 8004 |
| Pi-hole | ✅ Healthy | 8053 |
| Redis | ✅ Healthy | 6379 |
| PostgreSQL variants | ✅ Healthy | 5432 |

### Backup System
| Check | Result | Status |
|-------|--------|--------|
| Local backups | ✅ 10 pre_deploy backups | ✅ |
| Full backup | ✅ `/home/rohit/.hermes/backups/full_20260912_020248` | ✅ |
| OneDrive push | ❌ FAILED (Microsoft Graph API error) | ❌ |
| Backup rotation | `.hermes/backups/compose/` with 10+ entries | ✅ |

### Code Review Graph
| Check | Result | Status |
|-------|--------|--------|
| Nodes | 123,740 | ✅ |
| Edges | 1,087,987 | ✅ |
| Files indexed | 7,213 | ✅ |
| Risk score | 0.35 (low) | ✅ |
| Test gaps | `define_jobs` | ⚠️ |
| Last updated | 2026-09-08T16:10:46 | ⚠️ (stale) |

---

## Security Findings

### HIGH
1. **Credential files world-readable**: `.telegram_token`, `.duckdns_token`, `.grafana_password` have `-rw-rw----` permissions. Should be `600`.
2. **Missing `.mcp.json` registration**: 12+ MCP servers run in Docker but only 1 is registered in `.mcp.json`. This means MCP tool discovery is incomplete.
3. **`agentharness` directory deleted**: Multiple agent harness services (code-review-bridge, data-management, global-chat-mcp, graphify-mcp, hermes-memory-mcp, homelab-exec, infrastructure-services, mcp-gateway, synapse-mcp, system-monitoring) were decommissioned. Their compose declarations are kept but the actual code is gone.

### MEDIUM
4. **`hermes-scheduler.service` missing**: The systemd service referenced in HERMES.md doesn't exist. Jobs may not survive reboot.
5. **Healthcheck script duplication**: Two copies exist (`/home/rohit/scripts/healthcheck.sh` and `/home/rohit/.hermes/scripts/healthcheck.sh`), and the path in HERMES.md (`/opt/data/scripts/healthcheck.sh`) doesn't match either.
6. **OneDrive backup failure**: The backup to OneDrive failed on 2026-09-12. Local backup is OK but offsite redundancy is broken.

### LOW
7. **Graph staleness**: Code-review-graph was last updated 2026-09-08 (4 days ago). Should be refreshed.
8. **Docker compose command alias**: `docker-compose` not found, using `docker compose`. This is functional but could confuse scripts.

---

## Recommendations

### Immediate (Priority 1)
1. **Fix hermes-scheduler.service**: Create the systemd unit file or update HERMES.md to reflect the actual startup mechanism
2. **Fix credential permissions**: `chmod 600 /home/rohit/.hermes/.telegram_token /home/rohit/.hermes/.duckdns_token`
3. **Update `.mcp.json`**: Register all 12+ MCP servers from Docker containers
4. **Fix OneDrive backup**: Investigate Microsoft Graph API error

### Short-term (Priority 2)
5. **Add test coverage for `define_jobs`**: The only identified test gap
6. **Consolidate healthcheck.sh**: Remove duplicate, fix HERMES.md path reference
7. **Refresh code-review-graph**: Run `code-review-graph build` to update the graph
8. **Document decommissioned services**: Update `services/homelab/meta.yml` with current state

### Medium-term (Priority 3)
9. **Verify "106 jobs" claim**: Audit the actual total across all scheduling mechanisms
10. **Implement healthcheck.sh at `/opt/data/scripts/`**: Or update HERMES.md GROUNDING RULE
11. **Restore agentharness services**: If still needed, restore from backups

---

## Appendix: Live System State

```
System: Debian 13 (kernel 6.12)
CPU: AMD Ryzen 7 4700U (8 cores)
RAM: 62 GiB total, 26 GiB available
Storage: 221 GiB NVMe, 65% used (75 GiB free)
Containers: 27 total, all healthy
Telegram: ✅ (HTTP 200)
MCP Graph: 123,740 nodes, 1,087,987 edges
Risk Score: 0.35 (low)
Audit Date: 2026-09-12
```

---

*Report generated by Claude Code during deep audit session. See `/home/rohit/.hermes/audit/reports/` for historical audits.*
