# Relay Journal — 2026-08-06 (n8n ↔ bridge E2E wiring)

## Found: n8n ↔ bridge entirely broken (all 24 workflows)

The `n8n_bridge_server.py` (`~/.hermes/scripts/`, `n8n-bridge.service`, port 9199)
was bound to **`127.0.0.1` only**, but every n8n workflow (in Docker,
compose_default net, gw `172.18.0.1`, n8n IP `172.18.0.4`) calls
`http://172.18.0.1:9199/...`. The docker0 gateway → host loopback path was
**unreachable** → all workflows hit `ECONNREFUSED`. This silently broke the
whole Docker-driven automation: `Service Auto-Heal`, `SSH Login Monitor`,
`Scheduler Health Monitor` in constant `error`, and 9 more workflows
erroring daily (verified from inside n8n container: both `172.18.0.1:9199` and
`host.docker.internal:9199` failed).

## Fix applied (2 changes to `scripts/n8n_bridge_server.py`)

1. **Bind `0.0.0.0`** via `HOST = os.environ.get("N8N_BRIDGE_HOST", "0.0.0.0")`
   (was hardcoded `127.0.0.1`). Safe: no external NAT for 9199 (only
   3010/3004/8443/8118/53/8053 DNATs), private-LAN only. `systemctl --user
   restart n8n-bridge.service` → now `LISTEN 0.0.0.0:9199`.

2. **Trust internal sources for auth** — `check_auth()` now returns true for
   loopback/private/link-local client IPs (`_from_trusted_source()`).
   Workflows call `"authentication":"none"` but hit AUTH_KEY-required endpoints
   (`/run`, `/service-restart`, `/docker-restart`, `/prometheus-query`,
   `/cert-check`, `/backup-status`, `/service-logs`). Rather than embedding the
   Bearer token in 24 workflow configs, internal/docker sources are trusted
   (bridge is not externally reachable).

## Verification (all from inside the n8n container)

- `system-health`, `all-services-status`, `service-logs`, `backup-status`,
  `cert-check`, `disk-usage` → all **HTTP 200** with real live data.
- `/run` POST `{cmd:"echo hello-from-n8n && uptime"}` → 200, executed host cmd.
- `/telegram-send` → delivered msg to home channel (msg_id 6707).
- Workflow recovery confirmed: `Service Auto-Heal` + `SSH Login Monitor` went
  `error`→`success` at 11:35 PDT (11:30 run was the restart boundary). Decoded
  execution_data confirmed pre-fix errors were all `ECONNREFUSED` on
  `172.18.0.1:9199`. Remaining workflows (Scheduler Health Monitor 30-min,
  hourly/daily ones) will succeed on next scheduled run.

Commit: AgentChaguli `main` `1d6bf7d` (also adds `scripts/n8n_bridge_server.py`
to `main`; it previously only existed on the divergent `master` branch).

## Note: git branch split on AgentChaguli repo
`~/.hermes` default branch is `master` (legacy) but remote HEAD/active is
`main` (recent commits went there). Earlier session commits (2c583f5,
7eda9a7, 3b236fe) are on `main`; `master` is 126 commits divergent. When
committing future changes under `~/.hermes`, commit to **`chaguli/main`**
(authoritative), not local `master` — use `git worktree add` on `chaguli/main`
to avoid the dirty working tree blocking branch switches.