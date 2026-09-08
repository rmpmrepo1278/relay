# Xkiro wired into OmniRoute free fallback (2026-09-08)

## Objective
Add Xkiro (`https://api.xkiro.com/v1`, OpenAI-compatible, free-tier capacity) to OmniRoute's free LLM provider pool so the `pi-free-fallback` combo gains live capacity before the local executor tail.

## What was done
- Verified upstream directly: `GET /v1/models` returns 112 models. Not all are usable on the free tier:
  - Works: `minimax/minimax-m3:free`, `deepseek/deepseek-v4-flash`, `sensenova/sensenova-6.8-flash-lite`, `mistralai/ministral-8b`
  - Returns empty content: most `minimax/minimax-m2*:free`
  - `internal_error`: most `qwen/*:free`
  - `permission_denied` (paywall): `openai/gpt-5.3-codex-spark`, etc.
- Created connection in `provider_connections`:
  - id `e58e7038-af75-43e9-a317-9d161b0abd19`
  - provider `openai-compatible-chat-e58e7038-af75-43e9-a317-9d161b0abd19`
  - auth_type `apikey`, name/display_name `xkiro`, priority 0, is_active 1
  - `provider_specific_data` = `{"baseUrl":"https://api.xkiro.com/v1"}`
  - `api_key` encrypted with the same AES-256-GCM scheme OmniRoute uses: `enc:v1:<iv>:<cipher>:<tag>`, key = `scryptSync(STORAGE_ENCRYPTION_KEY, "omniroute-field-encryption-v1", 32)`. Verified decrypt round-trip MATCH before INSERT.
- Added 4 legs to `pi-free-fallback` combo (v5), inserted before the magnitude local-executor tail (`pi-fb-5`):
  - `xkiro-m3`   `openai-compatible-chat-e58e7038-.../minimax/minimax-m3:free`
  - `xkiro-dsf`  `.../deepseek/deepseek-v4-flash`
  - `xkiro-sst`  `.../sensenova/sensenova-6.8-flash-lite`
  - `xkiro-min8` `.../mistralai/ministral-8b`
- Restarted `omniroute.service` (sudo -n systemctl restart works), verified:
  - Direct pinned leg: `POST /v1/messages` x-api-key `sk-79bf69b...` + model `openai-compatible-chat-e58e7038-.../minimax/minimax-m3:free` → 200
  - All 4 Xkiro legs → 200 (deepseek/sensenova emit `thinking` blocks first)
  - Combo-as-model `pi-free-fallback` walk → served by `xkiro-m3`, call_log records provider=openai-compatible-chat-e58e7038, account=xkiro, combo_step_id=xkiro-m3
- DB backed up to `/home/rohit/.omniroute/db_backups/storage-pre-xkiro.sqlite`

## Notes / conventions learned
- `openai-compatible-chat-<uuid>` connections are self-contained: no `provider_nodes` row needed; `baseUrl` lives in `provider_specific_data`, auth via `api_key` (encrypted column). Matches apinex (`936e95e2-...`) and magnitude (`mag-480fb243`) pattern.
- Combo model entries are `providerId/<model>` strings; `model_capabilities` rows are NOT required for routing.
- `call_logs` table has `combo_step_id`, `provider`, `account`, `connection_id`, `requested_model` columns — useful for auditing which leg served.
- `auto/best-free` is a SEPARATE auto-routing virtual combo (walked by auto-routing, not by `pi-free-fallback`); looks through discovery providers. Combo-as-model (`"model":"pi-free-fallback"`) is the reliable way to force the fallback walk.
- Connection inserts must quote `"group"` (SQL reserved) and set `quota_visible=1`; `provider_connections` also has `last_ping_at`/`last_pinged_reset_key` columns.
- STORAGE_ENCRYPTION_KEY in `/home/rohit/.omniroute/.env`; encryption desc in server bundle `src/lib/db/encryption.ts` (`enc:v1:` AES-256-GCM, static scrypt salt).

## Status
- Xkiro live on homelab router `127.0.0.1:20128` as free fallback capacity. No further action required unless the user wants a dedicated `xkiro-*` combo or more legs (e.g. `mistral-small-2603`, `ministral-14b`, `deepseek-v4-flash` variants all also return 200).