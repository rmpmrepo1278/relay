# Magnitude local inference trialed and wired into hop chain (2026-09-05)

## Trigger
User pasted trending GitHub repos and asked which are worth looking into for the
homelab + agent setup; said "do it". Evaluated the list and prioritized
magnitudedev/magnitude (local inference server that works with Pi/OpenCode/Hermes/
OpenClaw/Codex/Claude Code/Cline).

## What I found on the homelab
- AMD Ryzen 7 4700U (8 cores), 62Gi RAM, node v22.23.2, npm 10.9.8, 56G free disk.
- Magnitude not installed. Installed CLI: `npm i -g @magnitudedev/cli` (bin landlined
  at `/home/rohit/.npm-global/bin/magnitude`; NOT on PATH — use full path).
- `magnitude service install` + `service start`: downloaded 46MB inference engine,
  detected **AMD Radeon via Vulkan (RADV RENOIR)**, bound `127.0.0.1:10100`.

## Model selection + performance
- Catalog: 22 compatible models (growth to 57). Chose **lfm2.5-8b-a1b:gguf:q4**
  (Liquid LFM2.5 8B-A1B Q4, 7.2GB, DSpark, advertised 16-22 tok/s) over qwen3.8-27b
  (24GB, ~1 tok/s — too slow on this CPU) and with substantially better speed/memory
  than the qwen3.5 line; matched our size/RAM budget.
- `magnitude catalog pull lfm2.5-8b-a1b:gguf:q4` (~7GB, ~5-6 min), `models load`, then
  decoded via `/tmp/mag3.json` timings: **prompt 38 tok/s, predict 28.8 tok/s**,
  TTFT 642ms, full 200tok gen ≈ 2.8s** — far faster than OMR→Ollama qwen3:8b (15-35s).

## Notable gotcha
- LFM is a reasoning model: emits `reasoning_content` first. With small max_tokens
  (≤~60) the model only reasons and returns `content: None` (hop auto-falls through).
  With max_tokens≳120 it emits real content (`\nCHEESE`, `\nHOP-MAG-OK`).

## Hop integration
- Added no-auth direct leg in `KNOWN_DIRECT`:
  `"magnitude": {"base":"http://127.0.0.1:10100/inference/v1/chat/completions","key":"","proxy":None}`.
  Client-build guard now accepts localhost bases without a key; Authorization header
  only emitted when key present.
- Chain updated: `...,bai/qwen3.8-flash,magnitude/lfm2.5-8b-a1b:gguf:q4,ollama/qwen3:8b`
  (magnitude = strong local fast fallback BEFORE the slow ollama leg).
- Deployed as hop.py + unit (backup `hop.py.bak-magleg`), restart.
- Verified: magnitude leg via hop 200 3.8s `HOP-MAG-OK`; chain first leg north-mini-code
  `CHAIN-OK` 1.7s; groq `GROQ-OK` 0.3s. All good.

## Persistence
- systemd **user** unit `~/.config/systemd/user/magnitude.service`, "Starts at login Yes".
- `loginctl show-user rohit → Linger=yes` so it autostarts on headless boot.

## Other repos verdicts (from the evaluated list)
- magnitudedev/magnitude — the one worth it. NOW INSTALLED + wired into hop chain.
- DietrichGebert/ponytail — cheap: 54% less code claims, works w/ Hermes+OpenCode+Claude.
  Low effort, worth a look on the Mac side later (deferred).
- affaan-m/ECC — agent harness perf (skills/instincts/memory/security); install
  `./install.sh --profile minimal` supports `--target hermes`. Deferred.
- WorldFlowAI/everything-claude-code — Claude Code toolkit, lower priority. Deferred.
- anthropics/skills, mattpocock/skills — snowball risk; skip unless specific need.
- blader/humanizer — mist detectors; unnecessary for private infra. Skip.
- NousResearch/hermes-agent — not our agent stack. Skip.
- ruvnet/ruflo — workflow-of-workflows market; reputational risk. Skip.
- fmtlib/fmt / nvm-sh/nvm — deps, not agenda. Skip.
- bikini/exploitarium — attack tooling; ledgers/logs show zero interest. Skip.
- BraveOPotato/FckSignups — junk; burn. Skip.
- anomalyco/opencode — user's own project; keep maintained, not installed-on-homelab.

## Outcome (final, evening same day)
- **ACTIVE = Gemma 4 26B-A4B (Q4 QAT)** (`gemma-4-26b-a4b-it-qat:gguf:q4`) — 17.8GB, no speculative
  acceleration, loads reliably in ~20s, benchmarks 12.3 tok/s predict / TTFT 1.5s / prompt 20.9 tok/s,
  real content; via hop: 7.5s `HOP-GEMMA-OK`. Chain id swapped (`magnitude/gemma-4-26b-a4b-it-qat:gguf:q4`),
  unit redeployed (backup `hop.py.bak-gemmalej`), groq + chain + gemma legs all re-verified.
- **Nemotron 3.5 Lightning 30B-A3B (Q4) FAILED** on this box: `models load` reaches "Loading", RAM grabs
  ~25-28G, then the worker dies ~90s in → `Failed - worker IPC read failed: failed to fill whole buffer`.
  Reproduced 3× incl. after full `service stop/start`. No OOM (MemoryMax=infinity), no dmesg/segfault,
  no journal errors, no core dumps, empty ~/.magnitude/logs. Probable synthetic-DFlash/weight-path issue
  on RADV RENOIR; no disable-acceleration flag exposed. Removed from disk (reclaimed ~24G).
- **LFM2.5 8B-A1B Q4 kept on disk** as fast-but-weak local backup (28.8 tok/s).
- Decode methods doc: None < MTP < DFlash < DSpark (speculative; speed-only, not quality).

## Next steps
- (maybe) connect magnitude to Hermes/OpenCode via `magnitude connections add` and A/B
  against the cloud-first chain to decide whether to promote magnitude earlier/alone.
- Ollama-vs-magnitude redundancy: magnitude trumps ollama in the chain (speed+quality); ollama
  container idle at 269MB — drop ollama from chain optionally.
- Deferred repo follow-ups only if wanted: ponytail (mac), ECC minimal (hermes), cherry-picked
  mattpocock skills, humanizer patterns folded into voice_guide.md.