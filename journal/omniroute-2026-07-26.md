# Journal — 2026-07-26

## OmniRoute Consolidation Complete

Deployed OmniRoute v3.8.48 as the unified LLM gateway, replacing LLM Proxy (8080) and FreeLLMAPI (3005).

### Changes Made

**Deployment:**
- Container `omniroute` from `diegosouzapw/omniroute:latest`, Docker host networking
- Port 20128 on 0.0.0.0 (host network — container shares host's network stack)
- Volume `omniroute-data` mounted at /app/data for persistence

**Ollama Integration:**
- Provider connection inserted directly into `provider_connections` SQLite table with:
  - auth_type: openai
  - baseUrl: http://localhost:11434/v1 (host networking enables direct localhost access)
  - models: llama3.2:3b, nomic-embed-text:latest
- Working model: `ollama/llama3.2:3b`
- Chat completions, models list endpoints all return 200

**Admin Access:**
- Password set: POST /api/settings/require-login
- Session created, API key generated: `sk-2311ee2c77ccec21-14422b-f7c8e0e7` (manage scope)
- INITIAL_PASSWORD persisted in server.env for container restart durability

**Client Configs Updated:**
- ~/.hermes/config.yaml → base_url changed from :8080 to :20128
- ~/.hermes/.env → FREELLMAPI_ENDPOINT → :20128
- agentharness/data/.env and .env.local → same
- .secrets/master.env → same

**Documentation Updated:**
- ~/CLAUDE.md, agentharness/CLAUDE.md, hermes-agent/CLAUDE.md
- Skills: homelab-ops, homelab-audit, homelab-triage, homelab-review, homelab-health-check-terminal, self-heal, llm-proxy-architecture, service-lifecycle

**Deprecations:**
- LLM Proxy on port 8080 (PID 3556930 python3 process) — killed
- FreeLLMAPI container on port 3005 — stopped and removed

### What OmniRoute Provides
- 80+ pre-configured models from free providers: aug/ (Auggie), oc/ (OpenCode), tllm/ (TheOldLLM), dgw/, pepper/, veo-free/
- Smart auto-routing (auto/best-*, auto/coding-*, etc.)
- Token compression, MCP/A2A support
- OpenAI-compatible API at /v1/chat/completions and /v1/models
- Management API at /api/* (requires API key with manage scope)

### Model Naming Convention
- Local Ollama: `ollama/<model-name>` (e.g., ollama/llama3.2:3b)
- Built-in free: `aug/`, `oc/`, `tllm/` prefix (e.g., aug/claude-sonnet-4.6)
- Smart routing: `auto/best-*`, `auto/coding-*`, etc.
