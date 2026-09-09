# Ollama fully removed — magnitude is the only local backend (2026-09-09)

## Context
A standalone systemd `ollama.service` (`/usr/local/bin/ollama`, `OLLAMA_VULKAN=1`) had been enabled on
2026-09-08 to run qwen3:32b-64k, but on this CPU-only box it was too slow (>60s timeout) and was
holding ~23GB RAM. User directed: remove Ollama entirely — only magnitude going forward.

## Removed (2026-09-09)
1. Stopped + disabled systemd `ollama.service`; deleted `/etc/systemd/system/ollama.service`.
2. Removed binary `/usr/local/bin/ollama` (44MB).
3. Removed 19GB model store `/usr/share/ollama/.ollama`.
4. Removed `ollama` system user + `/usr/share/ollama` home (group left: other processes run under it).
5. Deleted OmniRoute DB `ollama` custom node (`openai-compatible-chat-fb4e338b-...`) + its
   provider_connection (localhost:11434); cleaned any residual state.
6. Rebuilt/confirmed combos have no ollama legs (pi-free-fallback uses groq/gemini/magnitude etc).

## Effect
- Used RAM dropped 52Gi to 23Gi (~29GB freed); available 38Gi — enough headroom for magnitude to load the
  17.8GB `gemma-4-26b-a4b-it-qat:gguf:q4` model that previously couldn't fit.
- Port 11434 closed. Magnitude (loopback 10100/10110) is the ONLY local inference backend.
- Operational docs updated (homelab-infrastructure.md, MEMORY.md, relay-summary.md, rohit.md);
  historical journal/benchmark records left intact.

## Note
History of the earlier compose-based removal (2026-09-05) is preserved in these same files; this entry
records the final systemd/binary/data/user/DB removal.
