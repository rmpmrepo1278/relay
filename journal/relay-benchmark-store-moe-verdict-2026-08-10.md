---
created: 2026-08-10
confidence: high
source: relay session log
tags: [ollama, benchmark, memory-store, local-llm, qwen3-moe, gemma4]
---

# Relay: persistent LLM benchmark store + MoE verdict + gemma4:12b A/B

## New: canonical benchmark store
- Added `memory/benchmarks/llm-benchmarks.json` (versioned in this repo, exists on Mac + home-hp).
- Added reusable runner `bin/bench_llm.py` — measures eval tok/s, prompt-eval tok/s, load time,
  and native tool-call latency/correctness, then appends a self-describing (host+software) entry.
  Future hardware upgrades / new techniques: run `python3 ~/.hermes/collaborator-memory/bin/bench_llm.py <model>`.
- Updated `memory/MEMORY.md` index + `memory/databases.md` store table. See `memory/benchmarks/README.md`.

## MoE verdict (data-backed, recorded in store)
- qwen3:14b (MoE, 14B total / 3B active, Q4, 100% GPU) decodes at **2.4 tok/s** regardless of
  thinking on/off — HALF the speed of dense qwen2.5:7b (4.9). Tool call 54-61s vs 11s.
- Cause: Vulkan MoE decode path (expert routing / grouped GEMM) on Vega iGPU is the bottleneck.
  Sparse-active-param advantage needs real GPU bandwidth. **MoE is a dead end on home-hp.**
- qwen3:14b DELETED to reclaim 9.3GB (kept for record in the store).

## gemma4:12b A/B (in progress)
- User asked about "gemma 12b with MTP". Findings:
  - gemma4:12b (dense 12B, 7.6GB, native tools+thinking) IS available and fits the 12GB ollama limit.
  - BUT ollama MTP (multi-token prediction, ~90% faster) is **MLX/Apple-Silicon-only** (v0.31+);
    not available on our Linux/Vulkan runner. So no MTP speedup here — plain dense-12B speed expected.
  - Worth testing only as a QUALITY A/B vs qwen2.5:7b (12B dense > 7B dense for agentic quality).
- Pull + bench in progress; results will be appended to the benchmark store.

## Default local model (unchanged pending gemma4 A/B)
- **qwen2.5:7b** remains default: 4.9 tok/s, 11s tool call. llama3.2:3b (10.2 tok/s) = fast path.
