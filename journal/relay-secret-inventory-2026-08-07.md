Secret inventory + hygiene pass for homelab (rohit@home-hp), per user request.

## Secret inventory (sanitized scan)

Sources of secrets, all git-ignored:
- .hermes/.env + .hermes/.env.systemd -> OPENROUTER_API_KEY, GOOGLE_API_KEY,
  GOOGLE_FREE_API_KEY, GROQ_API_KEY, CEREBRAS_API_KEY, SAMBANOVA_API_KEY,
  OPENROUTER_API_KEY_2, TELEGRAM_BOT_TOKEN (and NVIDIA via provider_keys ref)
- services/docker/compose/.env -> ALERTMANAGER_TELEGRAM_BOT_TOKEN, PIHOLE_WEBPASSWORD,
  N8N_BASIC_AUTH_PASSWORD, N8N_ENCRYPTION_KEY, BOOKSTACK_APP_KEY,
  VAULTWARDEN_ADMIN_TOKEN, HC_SECRET_KEY, HC_SUPERUSER_PASSWORD
- services/data/provider_keys.env -> env-var *references* only (GOOGLE_API_KEY=${GOOGLE_API_KEY})
- .hermes/.telegram_token -> Telegram bot token
- .duckdns_token -> DuckDNS token
- /etc/letsencrypt/live -> TLS material (Traefik termination)

## Findings
1. NO hardcoded literal tokens anywhere: scanned live paths for sk-...,
   ghp_, xoxb-..., 40-char hex -> zero matches. All keys are env-file or
   env-var-backed.
2. NOTHING references vaultwarden for infra secrets: rg for "vaultwarden"
   across agent scripts + systemd units -> no hits. Vaultwarden is ONLY
   the user/browser password vault; it does NOT hold infra/API tokens used
   by services.
3. Live .env files confirmed git-ignored (.env rule + explicit lines).
4. Secret FILES (.telegram_token, .duckdns_token, .hermes/.env) git-ignored.
5. services/traefik/.env path already covered by gitignore (line 8 region).

## Fix applied
- .gitignore: added ~/.docker.env to "Credentials (never commit)" section (3cb2203).
  File currently absent on host, but rule prevents future leak.
- ~/.npmrc already ignored. No other credential dirs present (no ~/.ssh/id,
  ~/.aws, ~/.config/gh/hosts.yml, ~/.config/gcloud, ~/.config/rclone present).

## Env-delivery verification
- telegram_bridge reads tokens via os.environ.get (BRIDGE_AUTH_KEY, etc).
- systemd: homelab-research, n8n-bridge use EnvironmentFile=.hermes/.env;
  proxy-server uses agentharness/data/.env. So secrets flow disk->env, never
  embedded in code or committed.

## Recommendation to user (not yet enacted)
- Optional follow-up: centralize the per-service .env files under a single
  secrets dir (e.g. /home/rohit/.hermes/secrets/*.env) with one
  EnvironmentFile line each, so new envs are always git-ignored by one rule
  instead of relying on per-path entries.
