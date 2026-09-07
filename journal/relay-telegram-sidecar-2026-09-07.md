# Relay — Telegram sidecar telegram fix (2026-09-07)

## Outcome (this session)
"hi" to @ChaguliBot is now answerable via a **sidecar Telegram receiver** in the
n8n-bridge. Two real root causes were found and fixed along the way.

### Root cause 1 — hop MODEL_REMAP parser truncation (CRITICAL)
`hop.py` parsed `MODEL_REMAP` by splitting the whole env string on commas, but
values are comma-separated chains. Result: `haiku-4.5` mapped to a single cloud
model (`openrouter/cohere/north-mini-code:free`), which failed at OmniRoute
(404) — magnitude never entered the chain, so the default agent model returned
empty/404 for everything. This was silently breaking the agent reply path
(empty assistant replies everywhere). **Fixed** the parser (token-walk: a token
containing `=` starts a new key; bare tokens extend the current chain).
`haiku-4.5` now walks north-mini(fail) → poolside(fail) → openrouter-minimax
(fail) → nvidia/minimax-m3 (SUCCESS via OMR, ~2.6-4.5s warm) → magnitude
(last-resort fallback). Verified live.

### Root cause 2 — gateway Telegram adapter connect deadlock (known #63309)
Gateway hung forever at "Connecting to Telegram (attempt 1/8)": the connect
coroutine stops after the log line; loop timers/asyncio.wait_for/5s heartbeat
never fire; faulthandler shows main loop parked in `selectors.select`; all
threads idle. Adapter byte-identical between image and host source. Not a
network problem (standalone PTB init+start with fallback transport works in
<10s in-container). Also confirmed adapter's 60s pre-connect sleep at line 4321
is by design ("MUST wait ≥50s for stale session expiry"); 120s SIGKILL watchdog
explains the "UNCLEANLY (SIGKILL)" lifecycle entries (not real OOMs).

## Sidecar deployment (chosen direction: bypass gateway's builtin Telegram)
- `config.yaml`: `platforms.telegram.enabled: false` (gateway recreated from
  compose, boots clean — confirmed zero telegram log lines, not in platform
  state; NOTE: `docker restart` was NOT enough — needed `docker compose up -d
  --force-recreate gateway`, service name is `gateway` not `hermes`).
- `docker-compose.yml` n8n-bridge: `BRIDGE_TELEGRAM_POLLER=1`, `HOP_MODEL=haiku-4.5`.
- Bridge: `_magnitude_reply(text)` added; `_route_telegram_command` now sends
  non-command text to the model instead of "Unknown command"; Telegram Markdown
  escaped via `_md_escape`. Verified in-container: replies "Hello! How can I
  help you today?". Poller runs with no 409 conflicts (gateway no longer polls).
- Poller owns getUpdates exclusively now (bridge served from host-mounted
  /opt/data/scripts = /home/rohit/.hermes/scripts/n8n_bridge_server.py).

## Still flaky / follow-ups
- magnitude inference-worker cold load is pathological: has been seen at 41% CPU
  for 19+ min without serving; direct calls to :10100 hung 200s (previously
  MAG-OK 53.8s). Cloud minimax covers it; don't block on magnitude warm-up.
- `hermes chat -q` inside container: no final response printed in -Q mode
  (title-gen Request timed out + interrupt-queue hang) — agent CLI is a separate
  rabbit hole; sidecar bypasses it by calling hop directly. Revisit later if
  agent-grade replies (memory/skills) are needed on Telegram.
- User action required: send "hi" to @ChaguliBot to confirm end-to-end.
- GitHub repo deletion 403 (parallel workstream): user resolving via web UI.
- Another stale-ce fact from other context: `docker restart hermes` reloads
  config (mtime-cached live); to be safe use force-recreate after config edits.

## Ship-state
- hop (user/system unit `tokenjuice-hop`, restart via sudo systemctl restart):
  chain parser fixed, returns fast via minimax-m3.
- gateway: telegram disabled, healthy, api_server connected.
- n8n-bridge: poller + agent reply live, 9199 healthy.
- magnitude: acn/inference alive on 8642/10100; worker load flaky (fallback only).