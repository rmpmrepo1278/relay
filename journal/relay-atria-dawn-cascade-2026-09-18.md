# Relay — Atria Dawn Preview wired into cascade (2026-09-18)

User requested wiring in **Atria Dawn Preview** (100M free tokens), OpenAI-compatible,
single model `Atria-Dawn-Preview` at `https://api.atria-asi.ai/v1`.

## What was done

1. **Probed provider** — GET /v1/models → `Atria-Dawn-Preview`; chat completion works
   (returns `reasoning_content`, thinking-heavy model).
2. **OMR provider_connections row** (no provider_nodes row needed — matches coder pattern):
   - provider/id: `openai-compatible-chat-atria-dawn` / `atria-dawn`
   - auth_type `apikey`, is_active 1, test_status active
   - API key stored in `api_key` **encrypted `enc:v1:`** (AES-256-GCM, scrypt static salt
     "omniroute-field-encryption-v1", via `/tmp/omr_enc.js` — reimplementation validated by
     decrypting the existing groq key → `gsk_bp...`)
   - PSD: baseUrl `https://api.atria-asi.ai/v1` + browser customUserAgent (CF posture pre-empt)
3. **model_context_overrides** — `openai-compatible-chat-atria-dawn` / `Atria-Dawn-Preview`
   → 131072 (source manual) so OMR keeps the leg in compatibility filtering.
4. **Combo `pi-free-fallback`** — inserted `atria-dawn` leg at index 4
   (after groq block, before gemini-no-creds). Full order:
   groq ×4 → **atria** → gemini ×2 → openrouter/free → apinex ×2 → xkiro → ovh →
   coder30b → lfm.
5. **Hop `fast` fallback chain** — now `groq/qwen/qwen3.8-27b → atria → coder30b → lfm`
   (unit tokenjuice-hop.service MODEL_REMAP). Small/fast background tasks fall through to
   Atria free tier when groq is down.
6. Restarted omniroute.service (combo cache) + tokenjuice-hop.

## Verified (post-restart, through hop :8083)

- Direct atria leg: 200 / 1.7s, `Atria-Dawn-Preview`, content OK (reasoning 135 chars)
- Combo: 200 / 0.22s → groq (leg 0 wins as designed)
- anthropic /v1/messages `fast`: 200 / 0.28s → groq

## Files / mutations

- `/home/rohit/.omniroute/storage.sqlite` (+ `.bak-atria-*`): connection, context override,
  combo leg
- `/etc/systemd/system/tokenjuice-hop.service`: fast chain (+atria)
- DB backups kept; hop.py untouched this round.

## Notes

- API key value deliberately NOT written to memory (shared repo). Stored encrypted in
  provider_connections.api_key; recoverable via OMR `.env` STORAGE_ENCRYPTION_KEY decrypt.
- Atria model is thinking-heavy: its `reasoning_content` eats max_tokens budgets — the hop
  aggregation handles it; for direct use keep max_tokens ≥ 128.
- combo/pi-free-fallback is now effectively 14 entries.