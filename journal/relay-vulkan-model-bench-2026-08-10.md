---
created: 2026-08-10
confidence: high
source: relay session log
tags: [ollama, vulkan, igpu, local-llm, qwen, ornith, benchmark]
---

# Relay: Vulkan iGPU enabled + model benchmark (local LLM decision)

## Hardware reality (home-hp)
- AMD Ryzen 7 4700U (8c/8t Zen 2, 15W mobile APU), NO discrete GPU.
- Vega 7 iGPU (Renoir/RADV), shared 34GB DDR4 (~24GB free). 60+ containers competing.
- Before this session: CPU-only inference. Measured 1.3-3.2 tok/s across models.

## Change: Vulkan iGPU enabled for ollama
- ollama already had Vulkan backend + `radeon_icd.json` + `libvulkan_radeon.so` in-image.
- Added to ollama service in apps.yml:
  - `devices: - /dev/dri:/dev/dri`
  - env `OLLAMA_IGPU_ENABLE=1` (ollama DROPS integrated GPUs unless this is set!)
- Bumped container memory limit 8G -> 12G (8G cap was binding with Vulkan; qwen2.5:7b @ 32K ctx = 6.6GB).
- Result: "inference compute ... library=Vulkan ... type=iGPU total=24.5 GiB".

## Benchmark (Vulkan, num_ctx 4096, quiet box)
| model | tok/s | tool-call time |
|---|---|---|
| llama3.2:3b | 10.2 | 7s |
| mistral:7b | 5.0 | 20s |
| llama3.1:8b | 4.8 | 16s |
| qwen2.5:7b | 4.9 | 15s |
| ornith:9b | 4.0 | 37s |

- ~3.2-3.7x speedup vs CPU-only (3b: 3.2->10.2, 8b: 1.3->4.8).
- ALL 5 models returned correct `get_weather {"city":"Paris"}` tool call.
- New models pulled: qwen2.5:7b (4.7GB), ornith:9b (5.6GB, text GGUF).
- Model store remains the mounted host dir /usr/share/ollama/.ollama/models.

## Recommendation
- **Default local model: qwen2.5:7b** — best mix of tool-calling reliability + speed (4.9 tok/s, 15s tool call) among the 7-9B class; qwen2.5 is the recognized ≤8B tool-calling leader.
- llama3.2:3b: keep for fast/simple interactions (10.2 tok/s).
- ornith:9b: legit agentic-quality option (SWE-bench 69.4% @9B) but SLOWEST on this box (4.0 tok/s, 37s tool call); the MakeUseOf article ran it on an RTX 4060, not an iGPU box. Use only for batch agent jobs. Vision variant `robit/ornith-vision:9b` is a community build - skip.
- NOT yet wired into litellm/agentharness - still points at llama3.2:3b / llama3.1:8b fallbacks.

## Gotchas
- `OLLAMA_IGPU_ENABLE=1` is required or ollama silently drops the iGPU ("dropping integrated GPU").
- Container memory limit must be > model size + KV (12G for 9B @ 32K ctx).
- ollama container recreates kill in-flight `ollama pull` background jobs.
- `docker stats` mem may read low (cgroup accounting); trust `ollama ps` SIZE + a real generation.
