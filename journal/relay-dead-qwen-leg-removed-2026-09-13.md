# Relay — Dead qwen-8088 leg removed; empty-response watchdog loop resolved

**Date:** 2026-09-13
**Status:** done / healthy

## Trigger
User pasted ~20 repeated Telegram alerts: "🔴 LLM generates empty responses; hop + magnitude restarts did not recover" + night reports + scheduler job failures. Asked to find gaps and fix.

## Root cause
The OMR combo `pi-free-fallback` (id `8d53b452-5f5f-493d-9d0f-df018ded6bca`) still carried the **dead `openai-compatible-chat-local-qwen-8088/qwen3.6-35b-a3b` leg** at index 11 — the local qwen service was already stopped+disabled and its 23G model deleted (see cleanup journal). When free-cloud quota was exhausted and the combo walked to local legs, `coder30b` (8089) worked but the following dead 8088 leg hit a ~20s timeout, which the proxy watchdog read as "empty response" → it restarted hop + magnitude in a loop, each restart re-firing the Telegram alert.

## Fix (storage.sqlite / combos table)
- Dropped the dead `local-qwen-8088` leg from **2 combos**:
  - `pi-free-fallback` (13 → 12 legs; now `…coder30b-local → lfm-local`)
  - `local-executor` `mag-480fb243-local-exec` (1 → 0 legs; only had the dead leg)
- Confirmed 0 residual combos referencing `8088`.
- Restarted `omniroute.service` (started in 11.1s, active).

## Verification
- `auto/best-chat` via hop (8083): 200, "clean-path", 11.4s (via `poolside/laguna-s-2.1:free`).
- `proxy_watchdog.py --loop=60` (PID 2350874): consecutive "Generation probe: ok" every min, 0 errors.
- Load avg 0.95, Mem 33/62G used, 28G available (no swap pressure).

## Notes
- Watchdog runs as raw python (per request from Sep NG via sudo?), not the `proxy-watchdog.service` unit (unit shows inactive but process 2350874 is alive since Sep 12). Both forms healthy.
- hop: 358 models, 0 errors.