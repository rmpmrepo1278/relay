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
## Addendum: unified chain for ALL clients (same session, post  1st commit)
- Found three clients, two paths:
  - Claude Code (homelab): ANTHROPIC_BASE_URL=http://127.0.0.1:20128 (OmniRoute direct,
    Anthropic-compatible), model combo/pi-free-fallback -> was cloud-only, local tail dead
    (magnitude masked + magnitude-bridge inactive).
  - dsh: hop :8083 auto/chat -> chain. Hermes: hop :8083 (config.yaml base_url localhost:8083/v1,
    provider custom, models like haiku-4.5 -> hop MODEL_REMAP) -> same chain.
- Fix (OmniRoute side): kept Claude on OMR (full Anthropic thinking/tool semantics), repointed
  combo local tails to direct llama.cpp legs:
  - NEW provider_connections: local-qwen-8088 (direct llama.cpp qwen3.6-35b-a3b),
    local-lfm-8086 (lfm2.5-8b). Schema: id, provider=openai-compatible-chat-<id>,
    name, default_model, provider_specific_data={"baseUrl":"http://127.0.0.1:XXXX/v1",...},
    is_active=1, api_key="", created_at+updated_at ISO-Z.
  - combos: pi-free-fallback (8d53b452...) tail now local qwen35-a3b -> lfm (replaced dead
    mag-gemma leg). mag-480fb243-local-exec -> qwen35 leg. mag-lite-2f7f3019-local-exec-lite
    -> lfm leg.
  - DB backup: ~/.omniroute/db_backups/storage.sqlite.bak-local-tail (+ wal/shm).
  - OMR runs as orphaned init child (pid reparented), NOT systemd; restart = kill pid +
    nohup omniroute serve --no-open >/tmp/omr.log.   [2m📋 Loaded env from /home/rohit/.omniroute/.env[0m
  [2m📋 Loaded env from /home/rohit/.env[0m
  [2m📋 Loaded env from /home/rohit/.npm-global/lib/node_modules/omniroute/.env[0m
No PID file found, attempting port-based stop...
Server stopped. does NOT kill this instaance.
- Verified: mag-480fb243-local-exec streams from qwen3.6-35b-a3b model string on :8088.
  Anthropic /v1/messages combo/pi-free-fallback -> groq qwen3.6-27b (cloud first) OK.
  All three clients now: cloud-first combo -> local qwen35 -a3b -> lfm.
