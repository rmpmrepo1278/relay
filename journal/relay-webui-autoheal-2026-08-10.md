---
created: 2026-08-10
confidence: high
source: relay session log
tags: [openwebui, openviking, ollama, autoheal, reactor, consolidation]
---

# Relay: WebUI consolidation, openviking removal, auto-heal wired

## 1. OpenWebUI: 2 -> 1
- There were TWO instances: `openwebui` (apps.yml, `:latest`, on `monitoring` net,
  webui.db updated Aug 10) and `open-webui` (standalone stack at
  `/home/rohit/services/open-webui`, `:main`, on `traefik` net only, public domain
  `webui.chagulihome.duckdns.org`, webui.db stale Aug 4, broken
  `OLLAMA_BASE_URL=http://host.docker.internal:11434`).
- Kept `openwebui` (apps.yml). Added `traefik` network to it; repointed
  `/home/rohit/services/traefik/dynamic/open-webui.yml` service url to
  `http://openwebui:8080`. Removed the standalone stack (volume
  `open-webui_open-webui-data` preserved as safety; dir moved to
  `/home/rohit/services/open-webui.disabled`).
- SECURITY: consolidated instance now has auth enabled (removed `WEBUI_AUTH=False`,
  added `WEBUI_SECRET_KEY=<random hex>`, `DEFAULT_USER_ROLE=user`,
  `ENABLE_SIGNUP=true`, `DEFAULT_MODE=chat`). Local 8082 access now requires login too.

## 2. Inference engines: 2 -> 1 (keep ollama)
- `openviking` (host-net, port 1933) was unhealthy (503 on /health for ~6 days),
  had empty `ov.conf`, and NOTHING referenced it as a backend. Removed container,
  service block from apps.yml, data dir `/home/rohit/services/data/openviking`.
- Kept ollama as the single engine (llama3.1:8b, mistral:7b, llama3.2:3b,
  nomic-embed-text). No gap.

## 3. Auto-heal GAP found + fixed
- Gap: `consolidated_health.sh` only DETECTS unhealthy; `autonomous_fixer.py`
  runs every 30 min but delegates to a rate-limited Claude session. Nothing did a
  fast restart — openviking sat unhealthy 6 days.
- Fix: new `/home/rohit/agentharness/scripts/autoheal_check.py`:
  - restarts containers with `autoheal=true` label when unhealthy
  - 2 consecutive unhealthy checks to trigger + 15 min cooldown (no thrash)
  - state in `/home/rohit/.hermes/data/autoheal_state.json`, log in
    `/home/rohit/.hermes/logs/autoheal.log`
  - `AUTOHEAL_DRY_RUN=1` for dry-run
- Scheduled in `hermes_scheduler.py` as `autoheal_check` (`*/5`, tags reactor/monitor);
  scheduler restarted. Live-tested with a throwaway unhealthy container:
  strike -> restart -> cooldown all confirmed.
- `autoheal=true` label present on openwebui and now also ollama (added).

## Models inventory (Q3)
- Available in ollama: llama3.1:8b (Q4_K_M), mistral:7b, llama3.2:3b, nomic-embed-text (embedding).
- Wired: `ollama-local` -> `ollama/llama3.2:3b` at localhost:11434/v1
  (used in owl-alpha / local-smart / openrouter fallback chains); agentharness
  proxy `local` provider -> LOCAL_LLM_URL=localhost:11434 (disaster-recovery fallback,
  cloud providers are primary). OpenWebUI: user-selectable.
- NOTE: host clients hitting `http://localhost:11434` still work (docker-proxy ->
  ollama container).

## Refs cleaned
- `docker_ghost_check.sh` EXPECTED_PATTERNS: removed openviking.
- `research_engine.py` scoring dict: removed qdrant, open-webui, openviking.

## Rollback notes
- WebUI: `open-webui.disabled/` + `open-webui_open-webui-data` volume intact.
- Host ollama systemd service was disabled earlier (container owns 11434 now);
  re-enable with `sudo systemctl enable --now ollama` after removing the container.
