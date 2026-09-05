---
created: 2026-09-04
type: journal
---

# OMR free cloud routing: OpenRouter tier now live for consumers (via tokenjuice-hop)

Goal: give Hermes/Jarvis/delegates a working $0 cloud LLM path through OmniRoute, hop as the front door.

## Free-tier revival results (all probed live, 2026-09-04/05)
- **OPENROUTER works** — the only truly-live cloud free provider. Stored OMR openrouter key was dead and
  *different* from `.env`. Replicated OMR's `enc:v1` credential encryption (`scryptSync(STORAGE_ENCRYPTION_KEY,
  "omniroute-field-encryption-v1", 32)` = python `hashlib.scrypt(n=16384,r=8,p=1,dklen=32)`; AES-256-GCM;
  `<iv>:<ct>:<tag>`), wrote the alive `.env` key into `provider_connections.api_key` for the openrouter row
  (backup `db_backups/storage-pre-openrouter-key.sqlite`), restarted `omniroute.service`. Verified model:
  `openrouter/poolside/laguna-s-2.1:free` (non-reasoning coding model — clean content, 57 tokens, ~1s).
- `openrouter/z-ai/glm-5.2:free` + `openrouter/thinkingmachines/inkling-small:free` route OK at OMR but return
  empty content (reasoning models eat the token budget — same thinking-token issue as local qwen3). Not used as
  primary; hop treats empty-content as failure and falls through.

## Other providers (keyed, direct probes)
| provider | status |
|---|---|
| openrouter | 200 ALIVE (used) |
| gemini (gemini-2.5-flash) | 429 rate-limited (key live; retry later) |
| nvidia (meta/llama-3.3-70b-instruct) | 410 Gone (model retired; try a live id) |
| groq (llama-3.3-70b) / cerebras (gpt-oss-120b) | 403 — keys dead at provider |
| sambanova (DeepSeek-V3.1) | 402 no credits |
| auggie / ddgw / pepper / felo (builtin no-auth) | 502 noauth / 418 IP-blocked / dead upstream |

Note: agentproxy `-OK` on groq/cerebras = cascade masking riding openrouter, NOT those keys working.

## hop MODEL_REMAP → fallback chain
`agentharness-proxy`, `haiku-4.5`, `claude-sonnet-4-20250514`, `anthropic/claude-haiku-4.5`
→ `openrouter/poolside/laguna-s-2.1:free,ollama/qwen3:8b`
- Hope walks candidates in order; success = 2xx + non-empty aggregated content (chat / messages); otherwise next.
- `/v1/models` injects keys + chain targets (371). no-think auto-applied to ollama leg.
- Deploy pattern that works: `systemctl kill -s KILL` + `reset-failed` + `start` (graceful restart hangs).

## End-to-end verified (via hop :8083, 2026-09-05)
- `agentharness-proxy` openai shape → wire `poolside/laguna-s-2.1:free`, "E2E-CLOUD-OK", 3.6s, 63 tokens.
- Anthropic `/v1/messages` shape → text block, `end_turn`.
- SSE stream relay → clean chunks. `haiku-4.5` / `claude-sonnet-4-20250514` / `anthropic/claude-haiku-4.5` → laguna free.

## Delegate lever (not yet flipped — user decision)
`~/.claude/settings.json` on homelab still points `ANTHROPIC_BASE_URL=https://openrouter.ai/api/v1`
(paid path, model `anthropic/claude-haiku-4.5`). Flipping base_url → `http://127.0.0.1:8083` routes the
auto-fixer + claude sessions onto the free laguna→ollama chain.

## Open items
- Gemini retry after 429 window; nvidia needs a non-deprecated model id.
- groq/cerebras fresh keys / sambanova credit from user to fix 403/402.
- auggie/ddgw need dashboard login (NextAuth csrf-gated) or IP cooldown — externally blocked.
- OMR REST management auth unusable → DB edits are the supported automation path.