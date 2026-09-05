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
→ `openrouter/cohere/north-mini-code:free,openrouter/poolside/laguna-s-2.1:free,openrouter/minimax/minimax-m3:free,nvidia/minimaxai/minimax-m3,ollama/qwen3:8b`
- Chain walks candidates in order; success = 2xx + non-empty aggregated content (chat / messages); otherwise next.
- `/v1/models` injects keys + chain targets (371). no-think auto-applied to ollama leg.
- Deploy pattern: `systemctl kill -s KILL` + `reset-failed` + `start` (graceful restart hangs).

## Live-model replacement sweep (2026-09-05)
Direct-probed current ids from OMR `/v1/models` catalogs (true status, non-stream):
| provider | live now | dead |
|---|---|---|
| openrouter | `cohere/north-mini-code:free` ~1s · `poolside/laguna-s-2.1:free` · `minimax/minimax-m3:free` | laguna-xs 502, `openrouter/free` 502, gemma-4-31b-it:free 429, z-ai/glm-5.2:free (not in catalog) |
| nvidia (valid key) | `minimaxai/minimax-m3` 1.1s · `moonshotai/kimi-k3` 27.9s | all `nvidia/meta/llama-3.3-70b-instruct`-style old ids 404/410 |
| groq | — | 403 across ALL ids (key dead, not model): `groq/qwen/qwen3.6-27b`, `groq/groq/compound`, `groq/openai/gpt-oss-120b` |
| cerebras | — | 403 both ids (key dead) |
| sambanova | — | 402 no credits |
| gemini | key live but throttled | 429 on `gemini-flash-latest`, `-3.5-flash`, `-3.6-flash` |

→ Chain updated to verified-live ids only. groq/cerebras REQUIRE fresh keys (not a model fix); sambanova
needs credits; gemini needs the 429 window to clear.

## Delegate flipped to free path (2026-09-05)
`~/.claude/settings.json` `ANTHROPIC_BASE_URL`: `https://openrouter.ai/api/v1` → `http://127.0.0.1:8083`
(backup `settings.json.bak-paid-openrouter`). Model `anthropic/claude-haiku-4.5` remapped by hop.
claude-code-valid SSE confirmed (message_start → content_block_delta* → message_stop; `print('hello')`
delivered, 2.1s). End-to-end: `agentharness-proxy` → wire `cohere/north-mini-code:free`, 0.9s; `haiku-4.5`
anthropic shape → `DELEGATE-LIVE`, 1.0s.