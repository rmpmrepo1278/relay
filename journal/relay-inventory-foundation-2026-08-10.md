# Relay: homelab inventory foundation built + live

Date: 2026-08-10 | Status: foundation COMPLETE, n8n rewire pending

## What landed
- `services/bin/inventory.py` — single source of truth, DERIVED from KNOWN compose
  projects + enabled systemd user units + `services/homelab/meta.yml`. Emits
  `inventory/inventory.json`, `inventory/inventory.md`, `inventory/n8n/registry.json`.
- `services/homelab/meta.yml` — deployment-reality exceptions:
  - docker_run: pihole, code-review-bridge, agent-status-api (monitored, not orphans)
  - declared_not_deployed: core:pihole, agentharness:code-review-bridge,
    core:nginx-proxy-manager (retired; traefik is the active proxy)
- Systemd user: `inventory.service` (regen + `--check --alert`, SuccessExitStatus=1)
  + `inventory.timer` (every 5 min, Persistent) + `inventory-server.service`
  (static http.server serving `inventory/` on 127.0.0.1:9180).
- Legacy `proxy-server.service` (AgentHarness proxy :8080) DISABLED — superseded by
  agentharness-proxy.service.
- Committed `6706e40` to /home/rohit home-config repo, pushed chaguli/main.
  (Rebased onto d49953f; stash-pop of pre-existing WIP succeeded.)
- Generated outputs gitignored (`services/inventory/`, `services/bin/docker` 42MB
  static binary) — regenerated 5-min, served live at :9180.

## Fixes during tuning
- `docker ps --format json` is NDJSON → new `sh_ndjson()` parser (was silently empty).
- systemd oneshot units (homelab-backup.service on timer) no longer flagged as drift.
- `excluded_containers` kept for ignore-fully; NEW `docker_run` semantics = expected +
  monitored but not compose-managed.
- Drift baseline is now **clean (drift: False)** with `--check --alert` ready for the
  timer. No more noise; real drift (service dies) alerts.

## Next
- Rewire n8n workflows to consume `http://127.0.0.1:9180/n8n/registry.json`
  (replace hardcoded lists in Service Auto-Heal W8zCbFPiMImMnqdo, Container
  Auto-Heal Yblw4xU0q8JuUpup, then others). PENDING user go-ahead.
