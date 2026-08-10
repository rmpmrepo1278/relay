# Relay: registry consumers rewired — health check no longer hand-maintained

Date: 2026-08-10 | Status: DONE, all green

## Key finding (corrects prior assumption)
n8n "Service Auto-Heal" (W8zCbFPiMImMnqdo) and "Container Auto-Heal"
(Yblw4xU0q8JuUpup) have NO hardcoded service lists — they already pull
from the :9199 bridge (/all-services-status = live systemctl; webhook
alerts for containers). NO n8n surgery needed. The real divergent list
was `~/.hermes/scripts/system_health_check.py` (hardcoded SERVICES dict,
10-min timer, Telegram alerts).

## What changed
- system_health_check.py REWRITTEN to be registry-driven: monitored set
  derived from services/bin/inventory.py (compose + enabled non-oneshot
  systemd + meta.yml). Layers: systemd (auto-recover), containers incl.
  docker_run (alert-only; n8n owns restarts), meta proc/telegram checks.
  Reads generated inventory.json (5-min fresh); falls back to live build.
  Prunes stale state keys (17 old my:* keys dropped). --dry-run flag.
- inventory.py: emit container_name (compose service name != container,
  e.g. paperless -> a5b7a9ce8bc1_paperless), unit_type for systemd,
  pass-through cmd/port for meta checks.
- meta.yml: meta_services = mcp-server (proc) + telegram-gateway (telegram).
  bmoe-server DROPPED — fully retired (no unit, no process, no refs; was
  silently failing 384 consecutive). proxy-server port check dropped
  (covered by agentharness-proxy.service, port 8080).
- Commits: 0991975 (registry-driven health check), e5edb40 (perf: read
  file not live rebuild, 11s->instant). Pushed chaguli/main.
- Verified: systemd run "All services healthy", exit 0, 0 failed units,
  state=62 keys matching registry. inventory.timer/inventory-server/
  agentharness-proxy/system-health-check.timer all active.

## Notes
- agentharness-proxy.service runs the SAME command on 8080 as the old
  proxy-server.service (start_proxy.sh) — the old unit was truly redundant;
  port-8080 process is the NEW proxy (started 12:52).
- Meta entries carry state:ok (present=True) so drift --check stays clean;
  runtime health is evaluated live by the health check, not the drift
  detector (declarative vs runtime layers).
