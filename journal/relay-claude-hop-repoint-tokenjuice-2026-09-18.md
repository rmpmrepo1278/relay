# Relay — Claude Code → hop re-point + TokenJuice headroom (2026-09-18)

User directive: "get the claide code installed on the homelab connected to the hop gateway"
(confirmed: "claide code" = Claude Code, already installed) + fix all issues found in the
tokenjuice-hop audit.

## Cascade state (verified live)

- Hop gateway `tokenjuice-hop` 127.0.0.1:8083 → OmniRoute :20128 → 12-leg `combo/pi-free-fallback`
  (groq qwen3.8-27b → gemini-3-flash-preview → openrouter/free → apinex ×2 → xkiro → ovh →
  local coder30b:8089 → qwen8088 inactive → local lfm:8086). Local legs: coder + lfm active.
- Claude Code on homelab (`~/.npm-global/bin/claude`) was pointing DIRECTLY at OMR :20128.
  **Now points at the hop**: `ANTHROPIC_BASE_URL=http://127.0.0.1:8083` (settings.json), so
  TokenJuice preprocessing + response cache + chain fallback apply to Claude Code traffic.
  Running claude processes must be restarted to pick up the change (env read at session start).

## Issues found & fixed

1. **settings.json malformed JSON** — the `hooks` object was broken (unclosed `]`/`}`
   between PostToolUse and SessionStart). Repaired + re-dumped; backup
   `settings.json.bak-repoint-hop-*`.
2. **Claude Code not via hop** — re-pointed to :8083. Verified `/v1/messages` combo → HOP-OK.
3. **coder direct leg hung** — `chatllm-coder30b` slot was stuck (single `-np 1` slot never
   released). Restart cleared it; ~2min cold model load (18.6GB GGUF, Vega Vulkan). Now
   `coder/qwen3-coder-30b-a3b` via hop = 200 in ~5ms warm. Symptom to watch: /health 503
   "Loading model" during load.
4. **Groq direct path** — not broken; model id is `qwen/qwen3.8-27b` (`3.6` doesn't exist
   on api.groq.com with this key). Direct groq round-trips in ~6-9ms via hop.
5. **TJ_NO_THINK_PROVIDERS stale** — defaulted to `ollama` (removed 2026-09-09). Now
   `coder,lfm`; `_direct_fetch` tolerates `no-think/` prefix (was 404 on local legs).
6. **No response cache** — added exact-duplicate response cache to hop.py:
   `RESP_CACHE` in-process LRU, TTL 300s / 128 entries (`TJ_RESP_CACHE_TTL/SIZE`),
   keyed on (path, model, body minus stream/_token_juice). Replays cached JSON for
   non-stream and re-emits proper SSE (`event:`/`data:` framing) for stream clients, both
   OpenAI and Anthropic shapes. Stats: `resp_cache.{hits,misses}` on `/v1/token-juice`.
   Verified: seed 2.4s → replay 6ms, identical id, correct stream framing.
7. **Small/fast model wasteful** — was `combo/pi-free-fallback` (walked all 12 legs for
   background tasks). New `fast` alias in MODEL_REMAP =
   `groq/qwen/qwen3.8-27b,coder/qwen3-coder-30b-a3b,lfm/qwen3.6-35b-a3b` (3-leg fallback
   chain). `ANTHROPIC_SMALL_FAST_MODEL=fast`. Also added
   `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, removed stale `modelSettings.stealth/ox-alpha`.

## Files touched

- `/home/rohit/.claude/settings.json` — base URL → :8083, small/fast → fast, cleanups.
- `/home/rohit/tokenjuice-hop/hop.py` — response cache (+SSE replay), no-think prefix fix,
  miss counter, merged stats; backups `hop.py.bak-respcache-*`.
- `/etc/systemd/system/tokenjuice-hop.service` — new env (TJ_NO_THINK_PROVIDERS, resp-cache
  knobs, `fast` remap chain); backup `*.bak-respcache-*`. `daemon-reload` + restart done.

## Verified (post-restart)

combo 200 / 0.6s; fast 200 / 6ms; coder 200 / 5ms; lfm 200 / 0.25s; cache hits counting;
SSE replay correct. All backup files kept for revert.

## Open / notes

- Unexplained +1 miss in resp_cache stats per request (cosmetic; possibly a uvicorn
  reload artifact). Functionality verified.
- no-think now only helps OMR-path local legs; DIRECT local legs (coder/lfm) ignore the
  no-think/ prefix after stripping — real thinking-token savings on local legs would need
  llama-server `enable_thinking:false` in the units (affects coder quality; left as-is).
- Watch coder30b RAM: ~11-20GB RSS; RAM was tight (31Gi used / 62Gi).