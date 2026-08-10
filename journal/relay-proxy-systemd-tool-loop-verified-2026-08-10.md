# Relay: Proxy under systemd, tool loop verified (2026-08-10)

## Summary
- **Blocked→done**: agentharness-proxy now runs as a **systemd user service** (`agentharness-proxy.service`), so it survives ssh session teardown (the cause of repeated "Shutting down" deaths). Linger is already on (`loginctl` Linger=yes), so it also starts at boot.
- **End-to-end tool loop verified through the proxy**: `/v1/messages` → local gemma4:12b → Anthropic `tool_use` block in **6.1s**. `/v1/chat/completions` → qwen2.5:7b in 6.5s (provider local).
- **Bug fixed**: ollama native `/api/chat` returns tool-call `arguments` as an already-parsed **dict**; `proxy_server.py:546` assumed a JSON string → `TypeError` after the first successful local tool call. Added `_tool_args()` helper (handles dict/str/other) in `core/providers/proxy_server.py`.

## Unit file (`~/.config/systemd/user/agentharness-proxy.service`)
Modeled on `hermes-gateway.service` convention: `Type=simple`, `ExecStart=/home/rohit/agentharness/start_proxy.sh`, `WorkingDirectory=/home/rohit/agentharness`, `Restart=always RestartSec=5`, `RestartForceExitStatus=75`, `KillMode=mixed`, journal logging. Enabled (`default.target.wants`).

## Verification
```
systemctl --user is-active agentharness-proxy  → active (survives ssh end, still healthy)
curl :8080/health                             → {"status":"ok","type":"agentharness_proxy"}
verify_wiring.py tool loop                    → 200, 6.1s, tool_use {name weather_tool, input {location: Paris}}
verify_wiring.py chat local                   → 200, 6.5s, "pong", provider local
```

## Notes / follow-ups
- The model free-generated a plausible tool name (`weather_tool` + `location`) rather than following the provided `get_weather`/`city` schema exactly — gemma4:12b schema-following quirk, loop itself works.
- litellm process NOT running on homelab → the pending `litellm_config.yaml` fallback re-point to `ollama-agent` is **skipped as moot**; routing is handled directly in `proxy_server.py` (local-first: LOCAL_TOOL_MODEL / LOCAL_CHAT_MODEL).
- **Security**: `OPENROUTER_API_KEY_2/3` visible in plaintext in `agentharness/data/.env.local` (+ `data/.env.bak-20260801`) — redaction missed earlier. Not in git, but worth rotating/warning.
- Earlier one-off: first local tool call after proxy start returned empty + OpenRouter fallback 404'd; subsequent calls return tool calls reliably (warm-model state). No action taken; watch if it recurs cold.

## Files touched
- NEW `~/.config/systemd/user/agentharness-proxy.service` (homelab)
- `agentharness/core/providers/proxy_server.py` (homelab) — `_tool_args()` helper; `_tool_args` call at tool_use construction
