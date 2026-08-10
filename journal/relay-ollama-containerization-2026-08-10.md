---
created: 2026-08-10
confidence: high
source: relay session log
tags: [ollama, openwebui, docker, compose, containerization]
---

# Relay: Ollama containerization completed

## What was done
OpenWebUI could not reach Ollama (its `host.docker.internal` did not resolve, and
the `monitoring` network's gateway `192.168.96.1` timed out on port 11434). The
host ran Ollama as a bare systemd service (`ollama.service`) holding `*:11434`.

Completed the containerization:
1. **Stopped + disabled host ollama** (`sudo systemctl disable --now ollama`).
   Host clients (`LOCAL_LLM_URL=http://localhost:11434` in agentharness
   `.env.local`, the local `ollama-local` route) are preserved because the container binds
   `127.0.0.1:11434` and docker-proxy forwards to it.
2. **Mounted existing 11G model store** from host into container:
   `/usr/share/ollama/.ollama/models:/root/.ollama/models`. All 4 models carried
   over: llama3.1:8b, mistral:7b, llama3.2:3b, nomic-embed-text (so
   `llama3.2:3b` now actually exists).
3. **Fixed the broken `ollama` container** (had `{}` networks, no ports, no models
   — predated the fixed compose file). Recreated via
   `docker compose -f apps.yml up -d --force-recreate ollama` — now on `monitoring`
   network, `127.0.0.1:11434->11434`, healthy.
4. **Fixed healthcheck**: `ollama/ollama` image has NO `curl`, so healthcheck now
   uses `["CMD", "ollama", "list"]` (was failing "exec: curl not found").
5. **OpenWebUI**: `OLLAMA_BASE_URL` changed from bogus
   `http://host.docker.internal:8080` to `http://ollama:11434` (Docker DNS on
   `monitoring` network). Recreated; healthy; `docker exec openwebui curl
   http://ollama:11434/api/tags` lists all 4 models.

## Verified state
- `ollama` container: Up, **healthy** (status confirmed via `docker inspect`)
- `openwebui`: Up, healthy, connected to Ollama
- `hermes-memory-mcp`: still healthy with 10 tools at 8091
- Gateway `/mcps`: hermes-memory healthy/10 tools; all other MCPs healthy
- Host `curl http://127.0.0.1:11434/api/tags` still works (docker-proxy)

## Notes / gotchas for future sessions
- `apps.yml` lives at `/home/rohit/services/docker/compose/apps.yml`. It was once
  deleted by a bad sed/heredoc patch; there is a local backup
  `apps.yml.bak-1786300863` and `~/.hermes/backups/compose/pre_deploy_*` snapshots.
- The `monitoring` docker network (192.168.96.0/20, gateway .1) does NOT forward
  to host services even when the host binds `*:11434` — connection times out. Do
  not rely on gateway-IP access for cross container->host traffic; use Docker DNS
  or a containerized service.
- Ollama healthcheck: use `ollama list`, NOT `curl`.
- Host ollama models live at `/usr/share/ollama/.ollama/models` (11G). If models
  are ever pulled into the container, they land in the `ollama-data` volume at
  `/root/.ollama/models` — the host dir mount overlays it.
- To roll back: `sudo systemctl enable --now ollama`, remove the ollama service
  block + `ollama-data` volume + host-models mount from `apps.yml`, set
  `OLLAMA_BASE_URL` back.
