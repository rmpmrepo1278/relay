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
- AgentHarness LLM Proxy (8080, systemd user unit) — OpenAI-compatible proxy routing to direct free-tier providers (Groq, Cerebras, OpenRouter, Mistral, DeepSeek, Google, Cohere, Cloudflare, GitHub models) + local Ollama fallback
- Ollama (11434, host, `ollama.service`) — local inference; `OLLAMA_KEEP_ALIVE=-1`, `OLLAMA_NUM_THREADS=8`; models: qwen3:32b-64k (slow on 8 cores, 20GB) + qwen3:8b (5.2GB, warm ~1.5s, end-to-end via OmniRoute 15-35s incl. built-in thinking)
- Open WebUI (8082) — LLM chat UI
- Khoj (4321) — AI second brain with pgvector
- Qdrant (6333) — vector database
- OmniRoute (20128, systemd `omniroute.service`, v16.2.12) — **ACTIVE again** (2026-09-05; earlier note said REMOVED).
  Multi-provider gateway: 370-model catalog, OpenAI-compatible `chat/completions` + Anthropic `/v1/messages`,
  embeddings/audio/images/Responses APIs, combos/auto-routing, breakers, quota/credit system, free no-auth tiers
  (aug/ddgw/felo/pepper — currently down), custom openai/anthropic-compatible nodes, dashboard+CLI. Data:
  `/home/rohit/.omniroute` (storage.sqlite + `.env`). Custom node `ollama` → local Ollama: provider id
  `openai-compatible-chat-fb4e338b-cba4-4987-ad0a-bbd4e1a4558d`, connection `db7a77aa-...` (auth_type openai,
  PSD `{"baseUrl":"http://localhost:11434/v1"}`), prefix-routed model ids `ollama/<model>`. End-to-end verified
  (chat 15s, /v1/messages 35s). Queue budget: `RATE_LIMIT_MAX_WAIT_MS=120000` added to unit (default 15s too low
  for CPU Ollama).
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
