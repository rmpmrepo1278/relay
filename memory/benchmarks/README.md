# LLM Benchmark Store (home-hp)

Canonical, versioned record of local-LLM performance on the homelab, so numbers stay
comparable as hardware and inference techniques change.

## The data

- **[llm-benchmarks.json](llm-benchmarks.json)** — machine-readable source of truth.
  Each benchmark self-describes host + software (ollama version, runner, quant, ctx),
  generation stats (eval tok/s, prompt-eval tok/s, load time) and native tool-call stats
  (latency + correctness). Queryable with `jq` or any JSON tool.
- Git history in this repo gives a timestamped trail of every run and hardware change.

## How to run a new benchmark

```bash
# on home-hp (or anywhere ollama is reachable)
python3 ~/.hermes/collaborator-memory/bin/bench_llm.py <model> --ctx 8192 --note "..."
python3 ~/.hermes/collaborator-memory/bin/bench_llm.py qwen2.5:7b --reps 3
```

Flags: `--ctx N` (context, default 4096), `--predict N` (max tokens), `--reps N` (repeats),
`--think` (enable thinking mode), `--no-tool` (skip tool-call test), `--base URL`,
`--host NAME`, `--runner vulkan/cpu/...`, `--note "..."`.

The tool-call test uses a `get_weather` tool and asks for Paris — matching every run in the store.
After benchmarking, commit the store so the trail is versioned:

```bash
cd ~/.hermes/collaborator-memory && git add memory/benchmarks && git commit -m "bench: <model>" && git push
```

## Summary (2026-08-10, home-hp, Vulkan iGPU, num_ctx 4096)

| model | arch | tok/s | tool-call | verdict |
|---|---|---|---|---|
| llama3.2:3b | dense 3B | 10.2 | 7s | fast path |
| qwen2.5:7b | dense 7B | 4.9 | 11-15s | **DEFAULT** (best tool-call + speed) |
| qwen3:8b | dense 8B | 4.4 | 40s | quality option, slower tools |
| llama3.1:8b | dense 8B | 4.8 | 16s | — |
| mistral:7b | dense 7B | 5.0 | 20s | — |
| ornith:9b | dense 9B | 4.0 | 37s | batch jobs only |
| qwen3:14b | MoE 14B/3B-active | 2.4 | 54-61s | **DEAD END on iGPU** (deleted) |
| gemma4:12b | dense 12B + MTP | pending | pending | A/B in progress |

CPU-only baseline (pre-Vulkan): llama3.2:3b 3.2, llama3.1:8b 1.3 tok/s.

Key finding so far: MoE (sparse active params) does not speed up decode on the Vega iGPU
(Vulkan) — qwen3:14b was half the speed of dense 7B. MTP (multi-token prediction) in ollama
is currently MLX/Apple-Silicon-only; not available on this Linux/Vulkan box. See the
`notes`/`conclusion` fields in the JSON for each run.
