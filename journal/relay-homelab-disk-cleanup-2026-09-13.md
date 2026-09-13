# Homelab disk cleanup + hop rewire — 2026-09-13

## Before / after
- Disk: 152G used, 59G free (73%) → **111G used, 99G free (53%)**. Freed ~43G.

## Models removed (~38G)
| Model | Size | Why |
|---|---|---|
| Qwen3.6-35B-A3B-MTP (hub) | 23G | Old flagship, can't co-reside with coder30b, demoted in OMR |
| gemma-4-26B-A4B-it-qat (hub) | 15G | Service disabled; magnitude/gemma retired |
| LFM2.5-8B-A1B-DSpark (hub) | 531M | No service references |
| Qwen3.6-35B-A3B-DFlash (hub) | 402M | No service references |

Kept: coder30b manual (18G, port 8089, primary), LFM2.5-8B-A1B hub (4.9G, port 8086, fallback). Magnitude service still active + /health 200 (legs were error anyway).

## Caches cleared (~4.6G + apt)
- `/home/rohit/.cache/uv` 1.8G, `/home/rohit/.cache/trivy` 1.3G, `/home/rohit/.cache/ms-playwright` 1.3G
- `apt-get clean` (untouched — apt cache was already minimal)

## Hop rewire (qwen 8088 → coder 8089)
Removed qwen MTP model; qwen 8088 now dead. Updated routing so nothing dangles:
1. **hop.py**: added `coder` direct entry (127.0.0.1:8089), repointed all `auto/*` chains
   from `["combo/pi-free-fallback", "qwen/qwen3.6-35b-a3b", "lfm/lfm2.5-8b-a1b"]` to
   `["combo/pi-free-fallback", "coder/qwen3-coder-30b-a3b", "lfm/lfm2.5-8b-a1b"]`.
2. **tokenjuice-hop.service** (system unit): MODEL_REMAP env updated qwen→coder via sed.
3. Removed dead user units: `chatllm-qwen-a3b.service`, `chatllm-gemma26b.service`, `chatllm-gptoss20b.service`.
4. Restart gauntlet: the proxy-watchdog SIGKILLs hang on restart, so finished with
   `systemctl reset-failed + start`; watchdog then auto-recovered it (log: "Proxy recovered after restart").

## Verified
- `auto/best-chat` via hop → **qwen3-coder-30b-a3b**, replied "cleanup-ok" ✓
- OMR combo → transient empty once, then normal ✓
- All services active: coder30b, lfm, proxy-watchdog, tokenjuice-hop, omniroute, magnitude ✓

## Notes
- qwen MTP is gone permanently. coder30b is the only >=10B local model. If a Generalist
  ever gets added back, budget is ~18G RAM free (no swap pressure) for one more model.
- hop.py syntax validated with ast before deploy.
- MODEL_REMAP qwen→coder was the last dangling ref; grep confirmed none left.