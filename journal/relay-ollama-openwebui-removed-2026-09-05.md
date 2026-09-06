# Ollama + Open WebUI removed from homelab (2026-09-05)

## Decision
User asked: do we need both magnitude AND ollama? Evidence: chain tail had
`...,magnitude/gemma-...q4,ollama/qwen3:8b`; magnitude sits directly before ollama and is strictly
better (2.8s LFM / 12 tok/s gemma vs 15-35s OMR→ollama, incl. built-in thinking). Nothing else consumed
ollama except the hop chain (jarvis/hermes/OMR don't reference 11434). Recommendation: keep magnitude,
drop ollama.

## Discovery during teardown
- **Open WebUI** (:8082) was the other consumer — `OLLAMA_BASE_URL=http://ollama:11434` (apps.yml line 265).
  User confirmed "Remove both".
- Ollama held NO persisted models: `compose_ollama-data` volume = 24K, `/usr/share/ollama` = 4K (the qwen
  models were ephemeral/on-demand). Cheap to remove.

## What was removed
- `apps.yml`: `openwebui:` (255-294), `ollama:` (636-668) service blocks + top-level volumes
  `openwebui_data`, `ollama-data` → backup `apps.yml.bak-ollama-openwebui-2026-09-05`.
- Containers `ollama`, `openwebui` (`docker rm -f`); images `ollama/ollama:latest` (reclaimed 8.43GB)
  + open-webui (untagged/removed); volumes `compose_ollama-data` (compose_openwebui_data had already
  disappeared).
- Ports 8082 + 11434 verified free. systemd `ollama.service` was already inactive/disabled.
- Hop unit: chain tail `...magnitude/gemma-4-26b-a4b-it-qat:gguf:q4,ollama/qwen3:8b` → now ends at
  magnitude; removed `Environment=TJ_NO_THINK_PROVIDERS=ollama` (line 13). Deployed, daemon-reload,
  restart.

## Post-removal verification
- hop active; no `ollama` refs in deployed unit.
- Via hop :8083: chain → 200 3.7s `CHAIN-OK` (wire cohere/north-mini-code:free); gemma leg → 200 9.4s
  `GEMMA-OK` (wire gemma-4-26b-a4b-it-qat:gguf:q4); groq → 200 0.3s `GROQ-OK`. All good.
- Disk 49G → 65G free after removal.

## Leftovers (intentional, inert)
- OMR `ollama` custom node in storage.sqlite (provider `openai-compatible-chat-fb4e338b-...`) still
  points at dead localhost:11434 — no consumer routes to it (hop is the front door); left as-is.
- hop.py code keeps default `TJ_NO_THINK_PROVIDERS=ollama` (harmless; no ollama model is ever requested).