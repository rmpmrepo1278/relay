# 2026-09-11 — dsh web chat speed rescue (LFM 8B chat leg)

## Problem
dsh web chat on home-hp was ~2-6 min before first token. Root causes (measured):
- Magnitude's gemma-4-26b-a4b-it-qat prefills at ~54 tok/s through the AMD Vega
  iGPU (RADV/Vulkan, ~51 GB/s shared DDR4) → ~190s at 10.2K-token session context.
- The web profile injected the 86KB workspace `/home/rohit/AGENTS.md` into every
  prompt (agent-instructions) → ~366s TTFT.
- hop retried magnitude on failure (300s timeout × 2 attempts) → compounded.
- "Connection error" incidents were stale browser tabs whose socket died on
  service restarts, not server faults.

## Fixes applied (all live, reversible)
1. **Context cap**: `AGENTS.local.md` (3KB) at /home/rohit; agent-instructions
   candidates = [AGENTS.local.md], maxBytes/maxSourceBytes 8192. 86KB AGENTS.md
   left intact (other tools use it). Prompt now ~10.2K tok worst case.
2. **dsh-web.service** gained `WorkingDirectory=/home/rohit` (was `/` → {{cwd}}
   and file tools resolved under `/`).
3. **settings.yaml**: hop provider key is `apiKeyEnv: HOP_API_KEY` in this dsh
   build (README `ln:` is prose, zod-stripped). Default session model →
   `hop/auto/chat`.
4. **hop.py hardening**: magnitude direct timeout 300→120s; magnitude & lfm legs
   are not retried on chain attempt >0 (fail straight to combo).
5. **New chat leg — llama.cpp run directly for chat** (magnitude can't host LFM):
   - Magnitude 0.0.11 runtime has NO lfm2moe arch support → `models load
     lfm2.5-8b-a1b` silently re-boots gemma every start. Not a config pin.
   - Discovered too-late catalog note: `lfm2.5-8b-a1b:gguf:q4` = single-file
     LiquidAI/LFM2.5-8B-A1B-GGUF Q4_K_M; the sibling
     LFM2.5-8B-A1B-DSpark-GGUF (Q8 draft) FAILS catalog attribution.
   - `~/llama.cpp/llama-b10917` = llama.cpp 0.4.0-dev b10917 Vulkan build.
   - `chatllm-lfm.service` (user): llama-server --port 8086 -c 32768
     --no-webui --reasoning-format deepseek-legacy (thinking stays in content so
     consumers never see empty).
   - Perf: ~190-200 tok/s prefill, ~24 tok/s decode → cold 13K-token turn 54s
     (was 190s).
6. **hop routing for chat**: `auto/chat` alias → [lfm/lfm2.5-8b-a1b,
   combo/pi-free-fallback]. EXPLICIT auto/* aliases are now honored (task_router
   used to classify-override them — the reason auto/chat silently hit gemma);
   non-explicit still classify. auto/best-chat → magnitude/gemma unchanged
   (career-ops, watchdog unaffected).
7. **hop emptiness check**: now accepts `reasoning_content` as valid output and
   preserves it in aggregation (thinking models were misflagged "empty" when
   max_tokens consumed by reasoning only).

## Current topology
- hop 127.0.0.1:8083 → auto/chat → chatllm(lfm 8B) @8086; auto/best-* →
  magnitude(gemma 26B) @10100; combos → OmniRoute 20128.
- dsh web/headless default = hop/auto/chat. career-ops paths unchanged.

## Notes / landmines
- OmniRoute upstream account pool currently reports ALL_ACCOUNTS_INACTIVE
  (combo tail 503s) — combo is degraded; primary legs carry the load.
- llama.cpp in 0.4.0 renamed `--ngl` → `--n-gpu-layers`/auto device detection
  (`-dev`); `--reasoning-format` replaces legacy reasoning flags.
- systemd restart quirk: `reset-failed; start` does NOT restart an active unit —
  must SIGKILL, reset-failed, start (graceful stop hangs in "deactivating").
- Backups: settings.yaml(.bak,.bak-chatllm), cordis.patch.yml(.bak-greeting,
  .bak-context), hop.py(.bak-noretry-magtimeout,.bak-chatlfm,
  .bak-reasoning-nonempty), task_router.py(.bak-explicit-alias).

## Status
Web/headless on LFM chat leg verified end-to-end (headless e2e exit 0). Awaiting
user's browser hard-refresh + new-session confirmation.