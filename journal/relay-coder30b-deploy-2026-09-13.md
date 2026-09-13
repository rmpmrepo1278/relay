# Local coder30b + gpt-oss trial and coder30b deployment — 2026-09-13

## Decision from research (2026-09-12)
On our CPU-only homelab (Ryzen 7 4700U, 8C/8T, 2×32GB DDR4-3200, ~40 GB/s effective, 62Gi RAM, 16GB swap), the video-recommended **Qwen3.8 27B dense GSQ+RCO** (~11.8GB, 3.5 bpw) was a poor fit — dense 27B ≈ 3–4 tok/s on CPU. MoE is the correct architecture here. Researched candidates → executed "do it all".

## Models tested this session

| Model | Quant | File size | Warm tok/s | Verdict |
|---|---|---|---|---|
| Qwen3-Coder-30B-A3B (port 8089) | Q4_K_M | 18.6GB | **9.7–13.8** | ✅ DEPLOYED as primary local agentic coder |
| gpt-oss-20b (port 8090) | MXFP4 UD-Q4_K_XL then Q4_K_M | 11.9GB / 11.6GB | 1.3 → 0.45 | ❌ REMOVED — hopeless on this build |
| lfm2.5-8b (port 8086) | Q4_K_M | 4.6GB | 10.6–29.2 | ✅ kept as fast fallback |
| qwen3.6-35b-a3b MTP (port 8088) | UD-Q4_K_XL | 23GB | ~12 solo | ⏸️ stopped (can't co-reside) |

## Key findings
- **llama-b10917 is a Vulkan build.** All llama-servers run through the Vega iGPU (`vk::DeviceLostError` crashes under RAM overcommit). My earlier `strings` grep missed Vulkan symbols — the crash log (`ggml_vulkan: device lost on Vulkan0`) was the tell.
- **gpt-oss-20b is not viable here**: MXFP4 native = 1.3 tok/s; Q4_K_M solo = 0.45 tok/s + Vulkan DeviceLost crash even alone. Research estimated 14–18 tok/s — reality is ~1. Arch (gptoss MoE w/ 2:4 sparsity) has no fast CPU/Vulkan kernel path in this build.
- **RAM math is the hard constraint**: ~35GB services + models must fit in 62GB. coder30b (18.6) + lfm (4.6) = ~23GB works (8GB available). Adding qwen MTP (7.7 RSS) or gpt-oss (11.6) → ~0 available → Vulkan crashes + swap thrash (load avg 18).
- systemd `Restart=on-failure` auto-recovered coder after a DeviceLost — services self-heal.

## What was deployed
1. Downloaded `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` Q4_K_M (18.6GB) → `/home/rohit/.magnitude/models/manual/coder30b/coder30b-q4km.gguf`
2. New user services on homelab:
   - `chatllm-coder30b.service` (port 8089, `-c 65536`, `--cache-type-k q8_0 --cache-type-v q8_0`, `--alias qwen3-coder-30b-a3b`)
   - `chatllm-gptoss20b.service` (port 8090) — created then **disabled + model deleted** (not viable)
3. OMR DB (`/home/rohit/.omniroute/storage.sqlite`):
   - Added `local-coder-8089` (openai-compatible-chat-local-coder-8089) → active, default model `qwen3-coder-30b-a3b`
   - Added `local-gptoss-8090` → is_active=0 (kept for future)
   - Marked `local-qwen-8088` is_active=0 (qwen MTP stopped, can't co-reside)
   - Inserted `coder30b-local` leg into combo `pi-free-fallback` at index 10 (before qwen-a3b-local, before lfm)
4. Restarted omniroute — verified:
   - `combo/pi-free-fallback` → 200, model `openrouter/free`, 0.7s
   - direct `openai-compatible-chat-local-coder-8089/qwen3-coder-30b-a3b` → 200, `coder30b-ok`, 16.6s (cold)

## Final local stack (resident)
- **coder30b on 8089** — primary local agentic coder (~10–14 tok/s)
- **lfm on 8086** — fast fallback (~10–29 tok/s)
- qwen MTP (8088) + gpt-oss (8090) services exist but disabled/stopped; can be started manually

## Combo cascade (pi-free-fallback)
groq(DISABLED w) → gemini(no creds) → **openrouter/free** → apinex → xkiro → ovh → **coder30b(8089)** → qwen8088(inactive) → lfm(8086)

## Notes / follow-ups
- Watch RAM: coder30b + lfm co-resident leaves ~8GB. If a session needs qwen MTP, stop coder first.
- GPS-oss needs a newer llama.cpp with proper gptoss kernels (or GPU) to be worth retrying.
- Benchmark harness must use `enable_thinking: false` (chat_template_kwargs) or models burn max_tokens on reasoning_content.