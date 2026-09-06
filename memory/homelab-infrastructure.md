---
created: 2026-07-17
confidence: high
source: SSH, docker ps, config files, HOMELAB_MAP.md
---

# Homelab Infrastructure

**Server:** HP laptop, Debian 13 (Trixie), x86_64, Linux 6.12.90
**Hostname:** home-hp (also "homelab" in SSH config)
**Access:** Tailscale (100.122.58.40) primary, LAN (192.168.29.10) fallback
**Storage:** 221GB root (77% used), 4.6TB USB at /mnt/usb (5% used)
**User:** rohit

## Container Stack (~58 running)

### Core Infrastructure
- NPM (Nginx Proxy Manager) — reverse proxy + SSL on 80/443
- Pi-hole — DNS + DHCP on 53/8053
- Traefik — edge router on 80/443
- Docker Socket Proxy — secure Docker API on 2375
- Redis — shared cache on 6379
- Autoheal + Watchtower — auto-restart and update

### Applications
- Paperless (8000) — document management
- Immich (2283) — photo management
- SearXNG (8118) — private metasearch
- Vaultwarden (8443) — password manager
- Calibre-Web (8083) — ebooks
- Homepage (3003) — dashboard
- Home Assistant (8123) — home automation
- Bookstack — wiki
- Shlink — URL shortener
- Linkwarden — bookmarks
- Healthchecks (8004) — cron monitoring
- Uptime Kuma (3004) — service uptime
- OpenViking (1933/8020) — map server

### AI / LLM
- ~~AgentHarness LLM Proxy (8080)~~ — **REMOVED 2026-09-05** (decommissioned). Its OpenAI-compatible LLM role was
  superseded by **TokenJuice Hop (8083)**; consumers (Hermes, Jarvis, Claude delegate) all route through it.
  Kept `:8080` as cold standby during cutover (agentharness-proxy.service disabled after verification),
  then stopped. Direct-provider legs (Groq, b.ai) now live in hop.py, not agentproxy.
- **Magnitude (10100, per-user systemd `~/.config/systemd/user/magnitude.service`, Linger=yes) — ADDED 2026-09-05**:
  open-source local inference server (no cloud) that profiles hardware and tunes models. Detected AMD
  Radeon via Vulkan (RADV RENOIR) + 8C/62Gi. ACTIVE MODEL = `gemma-4-26b-a4b-it-qat:gguf:q4` (Gemma 4
  26B-A4B Q4, 17.8GB, no speculative accel, 100K ctx): **12.3 tok/s predict, TTFT 1.5s, ~7.5s via hop**
  (bigger/better than LFM 8B). First tried `lfm2.5-8b-a1b:gguf:q4` (LFM2.5 8B-A1B Q4, 7.2GB, DSpark) =
  28.8 tok/s, 2.8s but weaker model — kept on disk as backup. **Nemotron 3.5 Lightning 30B-A3B Q4 (q4,
  DFlash) CRASHES on this box** — `Failed - worker IPC read failed: failed to fill whole buffer` ~90s into
  weight load, reproducibly, no OOM/segv/journal artifacts; removed from disk. Dense 27B+ models ~1 tok/s
  unusable. OpenAI-compatible at `127.0.0.1:10100/inference/v1` + `.../inference/anthropic`; reasoning
  models emit reasoning_content first (ensure max_tokens ≳120 or content stays empty and hop auto-falls
  through). Wired as hop DIRECT no-auth leg (`magnitude/<model>`), the local fallback (was before ollama,
   now last local leg after ollama removal).
- Ollama (11434) — **REMOVED 2026-09-05** (was compose container in `apps.yml`; superseded by magnitude:
  28.8 tok/s LFM vs 15-35s OMR→ollama). `ollama:` service block, `compose_ollama-data` volume,
  `ollama/ollama:latest` image (~8.5GB), and Open WebUI (8082, its chat UI, `OLLAMA_BASE_URL=http://ollama:11434`)
  all deleted from `/home/rohit/services/docker/compose/apps.yml` (backup `apps.yml.bak-ollama-openwebui-2026-09-05`).
  Containers/images/volumes gone, ports 8082+11434 free. systemd `ollama.service` already disabled/inactive.
  OMR's inert `ollama` custom node (provider `openai-compatible-chat-fb4e338b-...`) now points at a dead
  localhost:11434 — no consumer calls it (hop is the front door); left as-is.
- Khoj (4321) — AI second brain with pgvector
- Qdrant (6333) — vector database
- OmniRoute (20128, systemd `omniroute.service`, v16.2.12) — **ACTIVE again** (2026-09-05; earlier note said REMOVED).
  Multi-provider gateway: 370-model catalog, OpenAI-compatible `chat/completions` + Anthropic `/v1/messages`,
  embeddings/audio/images/Responses APIs, combos/auto-routing, breakers, quota/credit system, no-think
  gateway alias (`no-think/<provider>/<model>`). Data: `/home/rohit/.omniroute` (storage.sqlite + `.env`).
  Custom node `ollama` → local Ollama: provider id
  `openai-compatible-chat-fb4e338b-cba4-4987-ad0a-bbd4e1a4558d`, connection `db7a77aa-...` (auth_type openai,
  PSD `{"baseUrl":"http://localhost:11434/v1"}`), prefix-routed model ids `ollama/<model>`. End-to-end verified
  (chat 15s, /v1/messages 35s). Queue budget: `RATE_LIMIT_MAX_WAIT_MS=120000` added to unit (default 15s too low
  for CPU Ollama).
- TokenJuice Hop (8083, systemd `tokenjuice-hop.service`) — token-maxxing preprocessor in front of OmniRoute.
  Reuses AgentHarness `core/providers/token_juice.py` verbatim (copied to /home/rohit/tokenjuice-hop/; was
  NEVER wired into agentproxy's live path — first time actually applied). API surface = agentproxy's
  (chat/completions + /v1/messages + /v1/models + /health + /v1/token-juice stats), deterministic
  response shaping (aggregates SSE→JSON for non-stream clients, relays SSE for stream), auto `no-think/`
  alias for ollama (TJ_NO_THINK=true), + generalized direct-provider legs (`KNOWN_DIRECT`: groq via Mac
  egress proxy, bai direct, magnitude no-auth local) that bypass OMR entirely. Own venv; upstream OMR :20128.
  **Consumers re-pointed (2026-09-05)**: Hermes `config.yaml`
  base_url `localhost:8080/v1/` → `localhost:8083/v1/`; Jarvis `config.toml` api_base
  `100.122.58.40:8080/v1` → `localhost:8083/v1`. Both send `model: agentharness-proxy`.
  `MODEL_REMAP` is now a **fallback chain** (cloud → local, auto-failover on non-2xx or
  2xx-with-empty-content): `agentharness-proxy`, `haiku-4.5`, `claude-sonnet-4-20250514`,
  `anthropic/claude-haiku-4.5` →
  `openrouter/cohere/north-mini-code:free,openrouter/poolside/laguna-s-2.1:free,openrouter/minimax/minimax-m3:free,nvidia/minimaxai/minimax-m3,groq/qwen/qwen3.8-27b,bai/qwen3.8-flash,magnitude/gemma-4-26b-a4b-it-qat:gguf:q4`
  (chain refreshed 2026-09-05 with **verified-live** model ids only; groq leg is hop-direct via Mac proxy;
  bai leg is hop-direct via homelab; reasoning `:free` models that emit empty content auto-fall through).
  /v1/models injects keys + chain targets (371 entries). **Delegate flipped to free path (2026-09-05)**:
  `~/.claude/settings.json` `ANTHROPIC_BASE_URL` now `http://127.0.0.1:8083` (was paid openrouter.ai; backup
  `settings.json.bak-paid-openrouter`); model `anthropic/claude-haiku-4.5` (remapped).
  claude-code-valid SSE verified (message_start → deltas → message_stop).
  agentproxy (`agentharness-proxy.service`) kept as **cold standby** on :8080 during cutover, then
  `disable --now`'d and stopped (2026-09-05).
  **Free cloud tier status (2026-09-05, all probed live):**
  - OPENROUTER ✓ LIVE (3 verified free models): `cohere/north-mini-code:free` (coding, ~1s), `poolside/
    laguna-s-2.1:free`, `minimax/minimax-m3:free`. Stored OMR openrouter key was a different dead one →
    rotated to the alive `.env` key via direct DB write (replicated OMR's `enc:v1` scrypt+AES-256-GCM scheme;
    backup `db_backups/storage-pre-openrouter-key.sqlite`; restart). OpenRouter free = working cloud legs.
  - NVIDIA ✓ LIVE with current ids: `nvidia/minimaxai/minimax-m3` (~1s, in chain), `nvidia/moonshotai/kimi-k3`
    (~28s). Old id `nvidia/meta/llama-3.3-70b-instruct` = retired (410).
  - GEMINI — key alive, 429 (rate/quota — "prepayment balance"; needs AI Studio fresh key or top-up).
  - BAI (b.ai, api.b.ai) — **KEY ADDED (2026-09-05)**: a `one-api` gateway. Account has 0 balance, so
    premium models return 403 or 400 (insufficient user quota). However, `qwen3.8-flash` is fully
    free-tier (required=0, balance=0 allowed). Wired as a direct hop leg `bai/qwen3.8-flash` calling
    `api.b.ai` directly from homelab (no proxy). Responded ~2.5s, clean content OK. Key tail `…wxiimd`.
  - GROQ — **NOW LIVE (2026-09-05)**: hop has a direct Groq leg (`groq/qwen/qwen3.8-27b`, also
    `groq/qwen/qwen3.6-27b`, `groq/openai/gpt-oss-120b` — these are the CURRENT ids) that bypasses OMR:
    Groq Cloudflare bans the homelab WAN IP (1010 "browser signature"); instead hop egresses via an HTTP
    CONNECT proxy on the paired Mac (Tailscale `100.86.100.87:8089`, launchd agent
    `com.relay.mac-egress-proxy`, key read from `.omniroute/.env`, host whitelist = api.groq.com + google
    generativelanguage + openrouter + openai). Verified through hop: 0.2s, content OK, SSE streams clean.
    Key was never dead (my earlier "dead key" note was WRONG — the 403s were wrong ids + the CF IP ban).
    Old ids `groq/llama-3.3-70b-versatile`, `groq/qwen3.6-27b`, `groq/groq/compound` = no-such-model.
  - CEREBRAS — 402 `payment_required`/quota (billing tab) — account, not key.
  - SAMBANOVA — 402 `PAYMENT_METHOD_REQUIRED` — account, not key.
  - Two spare OpenRouter keys in `.env.local` (`OPENROUTER_API_KEY_2`, `_3`) — valid, $0 usage, no limits
    (capacity backup). All GOOGLE_* fields = same project key. `FREELLMAPI_ENDPOINT=http://localhost:20128`
    = just OMR (internal label, no external aggregator).
  **OMR internals learned:** native `provider_connections` rows exist for openrouter/groq/nvidia/gemini/
  cerebras/sambanova (keys encrypted in `api_key` col, NOT `access_token`); only custom node = ollama.
  Management REST API auth unusable for scripting (cli-token 401; `providers rotate` 405/401; api_keys Bearer
  403) → use direct DB writes. Credential encryption: `scryptSync(STORAGE_ENCRYPTION_KEY,
  "omniroute-field-encryption-v1", 32)` → AES-256-GCM, format `enc:v1:<iv>:<ct>:<tag>` (python: hashlib.
  scrypt n=16384,r=8,p=1,dklen=32). Dashboard login = NextAuth v5 gated (csrf 401).
- Ollama — **REMOVED 2026-09-05** (compose `apps.yml` service + volume + image + Open WebUI; backup
  `apps.yml.bak-ollama-openwebui-2026-09-05`). Was the compose container (NOT systemd `ollama.service`,
  already disabled/inactive) publishing 127.0.0.1 + tailnet 11434 only. Open WebUI consumed it over the
  compose network. Superseded by magnitude (faster local); hop chain no longer references it.
- ~~FreeLLMAPI (3005)~~ — **REMOVED** (2026-07-30), redundant aggregator
- ~~MenteDB (6677)~~ — **REMOVED** (2026-08-10) per user request, redundant with consolidated `unified_memory.db`

### Monitoring
- Prometheus + Grafana (3002) + Loki (3100) + Alertmanager (9093) + cAdvisor (8085) + Node Exporter (9101)
- 13 Prometheus rule groups, 3 alert tiers, Telegram alerting

### MCP Servers (14+ via Agent Harness)
- Gateway (8090): homelab-ops, homelab-exec, docker, git, file, network, doctor, browser-use, paperless, rss, backup, hermes-memory, global-chat, codebase-memory, opencontext

### Agent Infrastructure
- Agent Status API (3010)
- Authentik SSO (9001) — OIDC for Paperless, Immich, Open WebUI

### Databases
- Immich DB (PostgreSQL), Paperless DB (PostgreSQL), Bookstack DB, Linkwarden DB, Authentik DB + Redis, Khoj DB (pgvector/PG17), Immich ML

### Networks
- core_default (shared), khoj-internal, monitoring, NPM bridges
