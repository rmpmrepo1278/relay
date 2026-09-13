# Local coder30b deploy + disk cleanup — 2026-09-13

## Outcome
**Freed 43G: 152G→111G used, 59G→99G free (73%→53%).** Homelab stack reorganized around a
single strong local agentic-coder leg (Qwen3-Coder-30B-A3B) instead of three overlapping MoEs.

## Models removed (~38G)
| Model | Size | Why |
|---|---|---|
| Qwen3.6-35B-A3B-MTP (23G) | 23G | Choked RAM in co-residency; coder30b replaced it. Service stopped+disabled. |
| gemma-4-26B-A4B-it-qat (15G) | 15G | Service inactive/parked; magnitude retired. |
| LFM2.5-8B-A1B-DSpark | 531M | No service references. |
| Qwen3.6 DFlash (402M) + gpt-oss MXFP4 file | 1G | Retired. |

Kept: **qwen3-coder-30b-a3b (18.6G)** + **LFM2.5-8B-A1B (4.9G)**.

## Why qwen MTP + gemma are gone
- Box is 62Gi total; services take ~35G. Only ~27G left for models.
- coder30b (18.6G) + LFM (4.9G) co-reside fine (=23.5G) with ~8G tailroom.
- qwen MTP (18.6G file + 23G hub dir) *cannot* co-reside: pushed RAM to swap, crashed
  the Vega Vulkan driver (`vk::DeviceLostError`), and DeviceLost-crashed llama.cpp while
  co-benchmarking. Real cost was infinite restarts + hop down.
- gpt-oss-20b: MXFP4 CPU path ~0.45 t/s, Q4_K_M solo ~1.3 t/s + DeviceLost — hopeless
  on this Renoir box. Deleted.

## Config rewired
- `auto/*` chains now: `["combo/pi-free-fallback", "coder/qwen3-coder-30b-a3b", "lfm/lfm2.5-8b-a1b"]`
  (local flagship → coder30b:8089 instead of qwen:8088).
- tokenjuice-hop `MODEL_REMAP` updated to point haiku/claude aliases at coder30b.
- Chromedriver/kvproxy ports unchanged.

## Disk monitors
- coder30b: **9.7–13.8 tok/s** (cold 16.6s→ warm 5.8s) — primary agentic coder.
- lfm: **10.6–29.2 tok/s** — always-on fast fallback.
- qwen MTP (11.9 t/s) and gpt-oss (1.3) both retired.

## Watchdog
The proxy watchdog SIGKILLs on restart — must restart via `sudo systemctl restart
tokenjuice-hop` with `sudo` so it doesn't self-heal-loop. Solved by wiring hop into
systemd user units + watchdog.

## Space reclaimed elsewhere
- Deleted qwen-a3b, gemma26b, gpt-oss service files (dead units).
- Cleared uv/trivy/playwright caches (~4.6G), apt cache.

## Next
- If RAM allows later (e.g. services shrink), consider adding back a small 8B generalist
  but nothing >30G is needed — coder30b + lfm cover the local tier.