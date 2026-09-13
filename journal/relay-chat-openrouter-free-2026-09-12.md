# 2026-09-12 — Chat routing fixed: openrouter/free meta-model + free-rate guardrails

**Status:** DONE (all live verified through OMR port 20128)

## What broke before this
- Claude Code (`~/.claude/settings.json` → `effortLevel: medium`) sends `reasoning_effort` in `/v1/messages`; groq rejected it with `400 "reasoning_effort" must be one of "none" or "default"`.
- All individual `openrouter/*:free` model slugs returned `404 "This model is unavailable for free"` for this key (account/region-level, not model-level).
- apinex was blocked by a stale `credits_exhausted` test_status after check-in.

## State before this change
- groq temporarily disabled: `provider_connections.is_active=0` for groq connection `9281136a-...` (weight=-1 in combos does NOT disable; is_active is the real kill switch).
- Combo `pi-free-fallback` reordered: locals (qwen 35B, lfm 8B) moved to last two positions, behind free cloud providers.
- apinex unblocked: cleared stale status on connection `936e95e2-...`; `free/gpt-5.6-luna` returns 200 (~2.5s).

## What this change does
1. **Combo openrouter leg swapped** (`pi-free-fallback`): `openrouter/meta-llama/llama-3.1-70b-instruct:free` (dead, 404) → `openrouter/openrouter/free` (OpenRouter meta-model that auto-routes to the best available free model; verified routing to `nvidia/nemotron-3.5-lightning:free`).
2. **Free-rate guardrails** so OMR can never hit paid OpenRouter even accidentally:
   - Connection already had `providerSpecificData.importFreeModelsOnly: true` (only `:free` models imported into catalog).
   - Added `providerSpecificData.quotaPreflightEnabled: true` (per-connection preflight).
   - Enabled env `QUOTA_PREFLIGHT_CUTOFF_ENABLED=true` in systemd drop-in `/etc/systemd/system/omniroute.service.d/quota.conf` → priority strategy honors quota cutoff (in-memory `openrouterFreeWindow`, seen in `combo.ts:957`).
3. Verified: `/v1/chat/completions` AND `/v1/messages` through `combo/pi-free-fallback` → 200, `x-omniroute-model: openrouter/free`, cost 0.0, ~600–1200ms.

## Free-window semantics (for when $10 tier kicks in)
- `open-sse/services/openrouterFreeWindow.ts`: 50 req/day (<$10) vs 1000/day ($10+); 20 RPM; self-corrects daily limit from server `X-RateLimit-*` headers (no manual tier flag needed). `setPurchasedTier()` exists but is in-memory/unwired — not needed here.

## Left as known issues (NOT regressions)
- ~129 error-level log lines during probing were the earlier individual-`:free`-slug 403/429s + partner legs (xkiro/gemini/ovh "No credentials"); after fix, `openrouter/free` stream completes ~1s.
- groq remains disabled; reasoning_effort at source: `~/.claude/settings.json effortLevel: medium`.
- `openrouter/free` occasionally lands on a 429-ing free model (e.g. `thinkingmachines/inkling:free`) but aggregate reroutes; combo falls to apinex/locals if needed.

## Journal refs
- Previous: 2026-09-12-free-fallback-cascade.md
- Files touched: `/home/rohit/.npm-global/lib/node_modules/omniroute/open-sse/translator/paramSupport.ts` (source-patched, unbuilt), `storage.sqlite` (combo + provider_connections), systemd drop-in.