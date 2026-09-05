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
## Key bounty + corrected provider story (2026-09-05)
Inventoried all keys on disk; probed each DIRECT from Mac IP + homelab IP:
- **GROQ key was never dead.** `403 error code: 1010` = Groq Cloudflare banning homelab WAN egress
  (73.239.85.189, "browser signature"), not the key. From Mac IP: auth passes, models live:
  `qwen/qwen3.6-27b`, `qwen/qwen3.8-27b` (content "ok"), `openai/gpt-oss-120b`.
- OMR→groq: breaker trips on the CF 1010 every call (log: "access denied | api.groq.com used Cloudflare
  to restrict access | ... errorCode 1010 ... Your IP 73.239.85.189"). Cleared breaker (DB
  backoff_level=0, test_status=active + restart) → still CF-blocked → re-arms. Groq unusable from homelab
  without a proxy (OMR proxy tables exist but empty) — could egress via Mac (Tailscale) if wanted.
- CEREBRAS = 402 `payment_required` (quota/billing), SAMBANOVA = 402 `PAYMENT_METHOD_REQUIRED` — account
  state, not keys. GEMINI = "prepayment balance" 429 — account/billing. All NOT fixable by swapping ids.
- Fresh OpenRouter keys `OPENROUTER_API_KEY_2`/`_3` valid ($0 usage, no limit) — spare capacity.
- `FREELLMAPI_ENDPOINT=http://localhost:20128` → it's OMR itself (was agentproxy's internal label).

## Signup reality
Automated account creation is not possible from here: every provider requires email verification link
access + (CAPTCHA) + first-party ToS acceptance — I have none of those. Wrapping this up with the user:
paths = (a) they paste fresh keys (AI Studio for Gemini fixes the quota line; Mistral/DeepSeek/Cohere/HF
gitHub/Cloudflare all add NEW free tiers), (b) browser-use MCP assist where they do captcha+email and I
handle the rest, (c) prep step-by-step scripts. Wiring any key = custom node (openai-compatible) + enc:v1
DB write + hop chain leg — the exact pattern already proven with openrouter/ollama.

## GROQ unblocked via Mac egress proxy (2026-09-05) — new free tier live
User chose "unblock Groq via Mac egress". Done end-to-end:
- Root cause: api.groq.com Cloudflare error 1010 bans homelab WAN IP (73.239.85.189, "browser signature").
  Key + models were fine (200 from Mac IP). OMR re-tripped its breaker on every groq call (empty streams).
- Built a CONNECT-only HTTP proxy on the Mac: `~/.local/bin/mac_egress_proxy.py`, binds Tailscale IP
  `100.86.100.87:8089`, whitelist {api.groq.com, generativelanguage.googleapis.com, openrouter.ai,
  api.openai.com}:443, launchd agent `com.relay.mac-egress-proxy` (KeepAlive, ~/.local/logs/egress-proxy
  .log). Classic CONNECT pitfall fixed: must drain request-headers up to blank line before 200, else the
  leftover `Host:` line is forwarded and api.groq.com answers plaintext `400`.
- hop.py gained a DIRECT groq leg: reads key from `/home/rohit/.omniroute/.env` (no new secret), issues
  groq chat via the proxy, aggregates SSE (non-stream) / relays (stream). Chain now:
  north-mini-code:free → laguna-s-2.1:free → minimax-m3:free → nvidia/minimaxai/minimax-m3 →
  groq/qwen/qwen3.8-27b → ollama/qwen3:8b. Verified: groq leg 0.2s "HOP-GROQ-OK"; stream relay has
  real chatcmpl/x_groq tokens.
- groq current ids: `qwen/qwen3.6-27b`, `qwen/qwen3.8-27b`, `openai/gpt-oss-120b`. Dead ids:
  `groq/llama-3.3-70b-versatile`, `groq/qwen3.6-27b`, `groq/groq/compound`.
- Corrected memory: groq was NOT a dead key (earlier note wrong).

## AgentHarness proxy decommissioned (2026-09-05) — consumers already moved
Answer to "do we still need agentharness?": the LLM proxy = NO, but the dir = only as legacy data.
- Verified each consumer path before stopping: hermes config.yaml base_url=8083 (hop); claude delegate
  settings base_url=8083; openjarvis config.toml `host=:8080` hits are its OWN engine ports
  ([engine.llamacpp]/[engine.uzu]) NOT the agentproxy — jarvis defaults to vLLM/GLM-4.7-Flash
  (localhost:8001) via its own engine registry. openjarvis.service still has a stale
  Wants/After=agentharness-proxy.service (harmless now that it's disabled; soft dep).
- Disabled + stopped agentharness-proxy.service (:8080 now free). Stopped idle start_dashboard.py
  (pid, port 9100, core.observe.dashboard admin UI — restartable via start_dashboard.py).
- Decoupled hop from the agentharness venv: created dedicated /home/rohit/tokenjuice-hop/.venv
  (uvicorn 0.52.4, fastapi 0.141.1, httpx 0.28.1 — httpx[proxy] extra no longer exists, `proxy=` is
  native in 0.28). Unit ExecStart now points there. Re-verified all 3 legs through hop (groq 0.3s,
  north-mini-code 1.7s, anthropic path 1.2s).
- Remaining attachment: agentharness/data/.env.local holds legacy keys (OpenRouter _2/_3 etc.) that
  other configs read — keep the dir until key migration; archive, don't delete.

## BAI key added & generalized direct hop (2026-09-05)
User pasted b.ai key (`sk-1cofzrjuw0ds5besngbw5jemncwxiimd`).
- Probed b.ai: `https://b.ai` is the static frontend (S3/CloudFront); the API base is `https://api.b.ai`
  (a one-api deployment). GET /v1/models works, but chat is premium-rate/deposit locked for most models
  (returns 403 premium, or 400 insufficient user quota e.g. deepseek-v4-flash required=4 credits).
  However, `qwen3.8-flash` is 100% free (required=0, balance=0 allowed) and returns fast completions.
- Refactored `hop.py` direct legs into a generalized map (`KNOWN_DIRECT = {"groq": {...}, "bai": {...}}`)
  and client cache to handle multiple independent direct routes cleanly without boilerplate.
- Appended `BAI_API_KEY` to `~/.omniroute/.env` (tail `…wxiimd`).
- Swapped unit service, restarted hop.
- Re-verified all paths: `bai/qwen3.8-flash` (200, 2.5s), refactored `groq/qwen/qwen3.8-27b` (200, 0.3s),
  and first-leg chain (200, 0.8s).
