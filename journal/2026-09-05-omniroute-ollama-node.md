# 2026-09-05: OmniRoute revived + Ollama node wired end-to-end

Context: auto-fixer lost its model (stealth/ox-alpha replacement pushed to laguna in Hermes catalog, but OpenRouter
account has $0 credits and all `:free` models are per-account rate-limited). User asked "can i use omnirouter?" —
it turned out OmniRoute (:20128) was NEVER removed; the memory note (2026-07-30 "REMOVED, redundant aggregator")
was stale. The systemd service (v16.2.12) had been running all along.

## What was wired

- Created custom provider node via REST (/api/provider-nodes, x-omniroute-cli-token = sha256(machineId + salt).
  CLI `nodes add` is broken — commander bug: node `--base-url` is shadowed by the global server `--base-url`.
- Node: `openai-compatible-chat-fb4e338b-cba4-4987-ad0a-bbd4e1a4558d`, prefix `ollama`, baseUrl
  http://localhost:11434/v1, apiType chat. Prefix-routed model ids: `ollama/<model>`.
- Provider-connections row `db7a77aa-...` (auth_type `openai`, test_status active, PSD `{"baseUrl":"http://localhost:11434/v1"}`).
  Gotchas found reading source (`src/sse/services/auth.ts`, `src/lib/providers/validation/urlHelpers.ts`):
  1. Credentials are keyed by provider = NODE ID, not the user prefix. Row must exist or routing says
     "No active credentials for provider: openai-compatible-chat-<id>".
  2. baseUrl MUST live in `provider_specific_data.baseUrl`. Empty PSD → executor defaults to api.openai.com → 401
     "You didn't provide an API key". (This was the confusing first failure.)
  3. For openai-compatible providers resolveChatUrl returns `{normalized}/chat/completions`; baseUrl must end in
     `/v1` → `http://localhost:11434/v1` (without /v1 it POSTs root → 404).
- Queue budget: default maxWaitMs=15000 too low for CPU Ollama (qwen3 thinking = 20-60s). Added
  `RATE_LIMIT_MAX_WAIT_MS=120000` to `omniroute.service` (unit backup `.bak-queue-20260905`).

## Local model reality check

- Ollama now serves qwen3:32b-64k (slow: 25s+ cold prefill, no parallel slots) — replaced-by qwen3:8b for speed.
- `qwen3:8b-instruct` tag doesn't exist; pulled `qwen3:8b` (5.2GB). Warm ~1.5s for short replies.
- Qwen3 ALWAYS thinks first (default); `"think":false` ignored via OpenAI-compat; TEMPLATE/SYSTEM tricks backfire
  (model emits literal `<think>` markers). Accepted thinking; raised queue. Empty `content` under tiny
  `max_tokens` caps (thinking eats the budget) — use `max_tokens` >= 200.

## End-to-end verified through OmniRoute

- POST /v1/chat/completions `ollama/qwen3:8b` → 200, content correct, ~15s.
- POST /v1/messages (anthropic shape, x-api-key dummy) → 200, `content:[{type:thinking},{type:text,"MSG-OK"}]`,
  stop_reason end_turn, ~35s. Claude-Code-compatible shape confirmed for the auto-fixer.

## AgentHarness proxy comparison (analysis delivered to user)

- agentproxy (:8080) is currently HEALTHY (overall healthy, cascade groq→sambanova→cerebras→mistral→openrouter→
  tokenrouter-*→owl→github-models→local), OMR free tiers all down (auggie not logged in, ddgw 418, felo/pepper
  dead, openrouter $0). Deprecation = downgrade until OMR free tiers revived.
- OMR unique: 370-model catalog, embeddings/audio/images, no-auth free tiers, quota/credit system.
- agentproxy unique: TokenJuice (HTML→MD, -40-80% tokens), response cache, reliability/usage/cost dashboards,
  runtime provider toggling; Jarvis (openjarvis.service) Depends on it; Hermes auth.json points at :8080.
- 6/6 API keys identical in both .env files. Deprecation path: revive OMR free tiers + prove reliability ~1 week,
  re-point consumers (:8080→:20128), keep agentproxy as cold standby, then retire.
- NOTE: agentproxy provider list still has a stale `stealth/ox-alpha` entry (removed only from the Hermes catalog).

## State

- OmniRoute active, ollama node+connection+queue verified. Backups:
  `/home/rohit/.omniroute/db_backups/storage-pre-ollama-conn.sqlite`, unit `.bak-queue-20260905`.
- Memory updated: homelab-infrastructure.md OmniRoute REMOVED→ACTIVE + Ollama model list. `omni_add_conn.py` /
  `omni_fix2.py` / `omni_fix_conn.py` left in `/home/rohit/` (re-runnable).