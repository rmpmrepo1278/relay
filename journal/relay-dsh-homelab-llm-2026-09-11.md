# Relay — DeepSeek Harness + local LLM chain resilience (2026-09-11 ~16:00Z)

## What the user asked
1. Install DeepSeek Harness (`dsh`) on the homelab and wire it to the local LLM (tokenjuice-hop, port 8083) — no API key needed while Modellix free-cloud access gets configured.
2. Fix the local chain producing only empty responses, and ensure any errors recover gracefully and automatically.
3. Journal the work and bring all documentation up to date.

## What I did
- Installed `@deepseek-ai/dsh@0.1.1-rc.2` (downgraded from 0.1.5-rc.1: `dsh-modellix@0.2.1` peer-targets ≤0.1.2-alpha.4, and `~/.npmrc` `min-release-age=14` blocks the 0.1.2-alpha.4 publish). PATH via `~/.bashrc`.
- Created user unit `dsh-web.service` → `http://127.0.0.1:3080` (loopback, `--no-open`; access `ssh homelab-cmd -L 3080:127.0.0.1:3080`). Modellix plugin installed; boot clean.
- Homelab context for every dsh session: `~/.dsh/AGENTS.md` + persona injection via `~/.dsh/profiles/web/cordis.patch.yml` (web-app bundle disables the host `agent-instructions` loader; the `system-prompt` persona is the always-on channel).
- `~/.dsh/settings.yaml`: provider `hop` → `http://127.0.0.1:8083/v1` (no-auth), default model `auto/best-chat`.
- **Root-caused the empty-chain bug**: task router returns UNKNOWN for short/ambiguous prompts → `auto/*` fell through with the bare alias → OmniRoute answered 200-with-empty-content → hop 502 `"chain returned only empty responses"` for every `auto/*` id.
- **Fixed hop** (chain resilience, 2026-09-11): `auto/*` now remap to magnitude → `combo/pi-free-fallback` (MODEL_REMAP + magnitude_map lists); empty-content guards on BOTH stream + non-stream; whole-chain retry ×2 with 2s backoff; failures logged.
- **Hardened watchdog** (generation probe + auto-heal): probes actual generation (`auto/best-chat`), 2 consecutive empties → restart hop → restart magnitude; `systemctl restart` hangs (strands unit `deactivating`) so restarts escalate SIGKILL+start; 180s rate-limit; Telegram alert.

## Verified healthy
- `auto/best-chat`: non-stream 200 content "OK" (gemma-4-26b); SSE real deltas; `qwen3:8b` + SIMPLE_CHAT 200.
- Watchdog cycle green every 60s (`Generation probe: ok … 0 errors`), `consecutive_empty: 0`.
- Controlled recovery test: `restart_service()` hung on plain restart → escalated → hop back healthy, probe green.
- dsh-web active, HTTP 200. No pre-existing errors in hop/watchdog logs.

## State
- **Caveats:** `combo/pi-free-fallback` (remote `qwen/qwen3.6-27b`) is still flaky (intermittently empty) — fallback tier only; magnitude is the dependable path and the watchdog auto-heal covers its loss. Modellix API key still pending (needs funded account). dsh pinned at 0.1.1-rc.2 (dev preview; `min-release-age=14` blocks newer).

## Docs updated
- `memory/homelab-infrastructure.md`: hop `auto/*` fix, watchdog probe/auto-heal, dsh stack.
- `hop.py` + `proxy_watchdog.py` docstrings.
- This journal entry.