# Qwen3.6-35B-A3B local flagship + cloud-first chains (2026-09-11)

Session forked from dsh-chat-speed day. Goal rephrased by user: LEVERAGE free cloud
providers first (apinex 1M/day etc.), cascade to local without capability loss, and
make the local heavy tier fast enough to be a real day-to-day workhorse (27-35B class).

## Hardware wall (measured, post-optimization)
- Ryzen 7 4700U + Radeon Vega iGPU (RADV RENOIR), 62GB unified DDR4-3200 **dual-channel 2x32GB**
  (dmidecode confirmed: 2 slots, dual-rank, 3200 MT/s) -> ~40GB/s effective = the hard decode wall.
- No hardware headroom (APU RAM clock locked). All wins below are software/model choice.

## GPU memory cap raised (the big unlock)
- Was: `ttm.pages_limit=6291456` (~25GB Vulkan carve) in /etc/default/grub -> blocked models >~24GB
  and caused `ggml_vulkan: device lost` / `ErrorDeviceLost` OOM at ~3.1K ctx on the A3B.
- Now: `ttm.pages_limit=10485760` (~40GB) via GRUB (`/etc/default/grub.bak-ttm`), `update-grub`, reboot.
- With the large carve the 22GB A3B fully offloads and coexists with LFM (verified post-boot).
- Reboot also recovered a Vulkan device-lost state that had killed ALL local legs.

## The model: Qwen3.6 35B-A3B (MoE, ~3B active, MTP head)
- Download: `magnitude catalog pull qwen3.6-35b-a3b:gguf:q4` (24.2GB) -> hub lands the
  **unsloth UD-Q4_K_XL** variant (22GB) + `mmproj-BF16.gguf` (multimodal). DFlash repo = 402M stub.
- Magnitude itself cannot serve it well (magnitude runtime is slow/limited) -> direct llama.cpp leg.
- **Bench (fully offloaded, direct llama.cpp b10917 Vulkan):**
  - baseline decode **9.9 tok/s**, prefill **73-84 tok/s** (long ctx)
  - vs magnitude gemma-4-26b: 5.5 tok/s decode, ~54 prefill  (2x at higher capability)
  - Gemma-4-26B direct llama.cpp was 8.0 tok/s (retired from chains anyway)
- **MTP self-spec (`--spec-type draft-mtp --spec-draft-n-max 2`): decode 10.6-12.7 tok/s (~+20-28%)**
  - acceptance 0.64-0.80, mean draft len ~2.3-2.6 (works on Vulkan for n-max 2)
  - **n-max 3 and `--spec-type ngram-mod` both hit the Vulkan partial-rollback bug
    (#22400): first token decodes, then silently stops -> NOT usable (reverted).** 

## Legs / units (all user systemd, ~/.config/systemd/user/)
- `chatllm-qwen-a3b.service` (ENABLED): llama-server :8088 -c 32768 -np 1 --no-webui
  --cache-reuse 256 --cache-type-k q8_0 --cache-type-v q8_0 --spec-type draft-mtp --spec-draft-n-max 2
- `chatllm-lfm.service` (ENABLED): llama-server :8086 -c 32768 (LFM2.5-8B-A1B fast leg, ~24 tok/s)
- `chatllm-gemma26b.service` (DISABLED, kept): Gemma 4 26B direct on :8087 — retired from chains, startable manually
- magnitude.service MASKED (was the slow gemma host) — unmask to restore
- CARVE NOTE: after a fresh llama-server restart the FIRST completion can return decode=1 token/empty
  (warmup quirk, not the Vulkan bug) — second call is fine.

## Routing (hop)
- Single canonical chain, cloud-first per user ask:
  auto/best-chat|best-coding|best-reasoning|best-fast|auto/chat -> [combo/pi-free-fallback, qwen/qwen3.6-35b-a3b, lfm/lfm2.5-8b-a1b]
- MODEL_REMAP updated identically for haiku-4.5/sonnet-4/agentharness-proxy/qwen3:8b + magnitude legacy id.
- magnitude/gemma completely removed from routing. hop.py added `qwen` direct provider (:8088),
  qwen timeout 600s (reasoning models are slow-but-fine). Backups: hop.py.bak-cloudfirst,
  tokenjuice-hop.service.bak-cloudfirst (system unit /etc/systemd/system/).
- e2e verified: auto/best-chat and auto/chat BOTH served by cloud first
  (`inclusionai/ling-3.0-flash-fin:free` — combo pool active again) — free cloud leads, local reserved.

## Free-cloud context
- apinex.bond reachable from homelab; `/v1/models` needs auth (401). User gets 1M free tokens/day
  via daily web login; apinex free legs already wired in combo (relay-omniroute-free-capacity journal).
- combo = OmniRoute :20128 (pi-free-fallback v8: apinex/xkiro/groq/nvidia/openrouter/ovh free legs + local tail).

## Misc
- Memory is already optimal (dual channel 3200) — no hardware lever. No better >25B engine for
  Vulkan iGPU (llama.cpp stays; MLC-LLM marginal; vLLM/ROCm n/a for gfx90c).
- Backups: grub .bak-ttm, hop.py.bak-cloudfirst, tokenjuice-hop.service.bak-cloudfirst;
  chatllm unit files have no explicit .bak but ExecStart is in this file.