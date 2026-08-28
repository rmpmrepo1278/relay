---
created: 2026-08-28
confidence: high
source: hands-on debugging session
---

# Telegram Gateway Connect Fix (2026-08-28)

## The Bug
Hermes gateway stayed in `TG: retrying` forever. Telegram adapter failed with
`telegram connect timed out after 30s` on both initial and reconnect attempts.

## Root Cause
TWO distinct timeouts were in play:

1. **Gateway-side connect timeout** — `gateway/run.py:_platform_connect_timeout_secs()`
   caps `adapter.connect()` with `asyncio.wait({task}, timeout=T)`.
   - If `platform == Platform.TELEGRAM`: initial=300s, reconnect=180s
   - Otherwise (non-Telegram): **30s default**
   - The observed 30s timeout meant the Telegram platform check was NOT matching,
     so Telegram fell through to the 30s generic default.

2. **Adapter-side 60s sleep** — `adapter.py` in `pre-connect` deliberately sleeps
   `60s` after a stale-session purge (`getUpdates?offset=-1`) so Telegram's
   server-side long-poll session from a SIGKILL'd prior gateway expires. This
   60s sleep alone exceeds a 30s gateway budget.

Because the gateway gave the Telegram adapter only 30s (generic default), the
adapter's 60s sleep always blew the budget → connect never reached
`app.initialize()`.

## The Fix
Set `HERMES_GATEWAY_PLATFORM_CONNECT_TIMEOUT=300` in the gateway service env
in `/home/rohit/docker-compose.yml`. This env var is checked FIRST in
`_platform_connect_timeout_secs()` and overrides all per-platform defaults,
giving the adapter a 300s budget that comfortably covers the 60s sleep + retry
ladder.

Also set (in compose env, not just `/opt/data/.env` — process env is what the
adapter/gateway see at runtime):
- `HERMES_TELEGRAM_INIT_TIMEOUT=120` (per initialize attempt)
- `HERMES_TELEGRAM_DISABLE_FALLBACK_IPS=1`

## KEY LESSON — dotenv vs process env
`load_hermes_dotenv()` (called at import from `hermes_cli/main.py`) loads
`/opt/data/.env` into Python `os.environ` — but only for modules imported AFTER
the load, and it does NOT populate `/proc/PID/environ`. Adapter code that reads
`os.getenv(...)` at module-import time or in methods that run before/during
dotenv load may see NOTHING. **Reliable fix: put operational env vars directly
in the docker-compose `environment:` block** so they are real process env vars
from container start. Do not rely on `.env` for runtime adapter/gateway knobs.

## Result
`gateway_state.json` shows `telegram.state = "connected"`. The long-standing
`TG: retrying` blocker is cleared.

## Still To Verify
- Message dispatch: send a message from Rohit's account (user 8607397452) to
  the Chaguli group and confirm `active_agents > 0` and an agent reply.
- The `sentinel-agent hook error: /opt/data/.hermes/hermes-agent` remains.
- AgentHarness proxy uptime (cloud providers exhausted).
