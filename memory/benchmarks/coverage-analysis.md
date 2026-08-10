# Local LLM Coverage Analysis (2026-08-10)

Estimate of how much of Rohit's past interaction load could be handled by the homelab's local LLMs.
Method: stratified sampling (~300 interactions across three sources), archetype classification,
then per-archetype success rates grounded in measured tool-call results + model benchmark deltas.
NOT a live replay. "Success" = correct AND complete (partials count as failures).

## Corpus profile
| Source | volume | character |
|---|---|---|
| Hermes/Telegram (state.db) | 1,841 user msgs | 17% scheduled, 16% simple QA, 15% infra ops, 15% health checks, 11% personal/career, 8% research, 5% data queries; ~70% of assistant turns are tool-driving (78% terminal) |
| Claude Code (homelab) | 157 sessions | 58% Hermes AUTO-FIX remediation, 40% smoke tests, rare long coding |
| opencode (Mac) | 2,069 prompts | 30% continuations, 26% questions, 11% bug-fix, 8% infra/shell, 7% data analysis, 7% feature/refactor; 51% short sessions; 10.8% long-context; ~0.1% images |

## Estimated success rate
| Source | qwen2.5:7b | gemma4:12b |
|---|---|---|
| Hermes/Telegram | ~79% | ~87% |
| Claude Code (autofix + smoke) | ~86% | ~92% |
| opencode (real coding) | ~66% | ~73% |
| **Overall (volume-weighted)** | **~73%** | **~80%** |

## Why the spread
- Agent/monitoring + autofix templates are extremely local-friendly (85-92%) — structured, tool-driven, short.
- opencode is where deep multi-file code work happens (lowest coverage, ~66-73%) and drags the weighted total.
- Residue (~20-27% for gemma4, ~27% for qwen2.5) = deep refactors, research synthesis, high-stakes writing.
  Cloud models (gpt-5.x, claude, gemini) stay the right call there.

## Caveats
1. Estimates, not replays — archetype rates, not live re-runs.
2. Latency separate from capability: gemma4:12b 2.7 tok/s, qwen2.5:7b 4.9 tok/s — long outputs feel 3-6x slower than cloud.
3. Tool-call correctness measured in this store: both models 100% on get_weather; gemma4:12b 7.5-9s, qwen2.5:7b 11s.

## Routing conclusion (wired 2026-08-10)
- **gemma4:12b** → agent tool-loops (Hermes/agentharness local brain) — fastest measured tool round-trip, best agentic coverage.
- **qwen2.5:7b** → chat/general local default (best tok/s + solid tools).
- **Cloud** → hard residue (deep code, research synthesis, career writing).
- llama3.2:3b → fast/simple path (10.2 tok/s).
