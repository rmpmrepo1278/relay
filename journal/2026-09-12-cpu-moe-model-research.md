# 2026-09-12 — Best CPU-only MoE LLMs for the Renoir box (4700U, 2ch DDR4, 19-35GB RAM free)

**Status:** DONE (research only, no code). For the agentic coding/assistant role.

## The rule (bandwidth-bound CPU)
Speed on CPU ≈ effective memory bandwidth / active-bytes-per-token. Total size only sets RAM needed.
BUT: 2026 hybrid Gated-DeltaNet MoEs (Qwen3.5/3.6/3.8) run ~3-5x SLOWER on llama.cpp CPU than
classic-MoE (qwen3moe/cohere2moe/gptoss/gemma4/laguna) at equal active params (llama.cpp#19480).
=> Prefer classic-MoE at 3B active on this box. GDN models ~6-9 t/s; classic ~12-16 t/s est.

## Verified facts (Sept 2026)
- No open Qwen3.7 weights (first closed flagship gen; Max/Plus/Flash API-only).
- Qwen3.8 open MoE = Flash-Next only: 176B checkpoint (125B+51B ngram), 6B active => too big.
- No official 60B-A6B exists anywhere. Only near-one: LLMWildling/gemma-4-60b-a6b-coder (MXFP4, NO GGUF, skip).
- Open A3B-class candidates with GGUF + llama.cpp:
  Qwen3-Coder-30B-A3B (18.6GB Q4) — safest pick, mature qwen3moe
  CohereLabs/North-Mini-Code-1.0 (18.7GB Q4, cohere2moe, b9626+) — SOTA agentic coder, Apache-2.0
  poolside/Laguna-XS-2.1 (20.3GB Q4, needs llama.cpp PR#25165 build) — highest small-MoE coding scores
  openai/gpt-oss-20b (11.3GB MXFP4) — smallest/fastest, generalist+tools
  google/gemma-4-26B-A4B (14-16GB Q4, day-one llama.cpp; QAT Q4_0 for CPU) — best generalist agent
  Qwen/Qwen3.6-35B-A3B (22GB, GDN-hybrid) — most capable but worst CPU speed; KV tiny (22KiB/tok)
- Too big for this box: Laguna-S-2.1 (75GB Q4), gpt-oss-120b (~60GB), Qwen3.8-Flash-Next (~100GB), Qwen3-Coder-Next-80B (45GB).
- Current RAM: 62GB total, 19GB free (services). Free up to ~35GB max => all A3B candidates fit.

## Decision support
Ranked capability-per-speed for agentic coding on this box (single interactive session):
1 Qwen3-Coder-30B-A3B · 2 North-Mini-Code-1.0 · 3 gpt-oss-20b · 4 Gemma-4-26B-A4B · 5 Laguna-XS-2.1 · 6 Qwen3.6-35B-A3B.
CPU-only: ignore --cpu-moe/-ncmoe (GPU-only knobs). Use Q4_K_M, flash-attn, q8_0 KV, -t 8, --mlock.

## Open loop
Bench 2-3 on the actual Renoir before committing (esp. Qwen3.6 GDN speed, North Mini vs Qwen3-Coder
tool-call reliability). Sources kept in the session transcript.