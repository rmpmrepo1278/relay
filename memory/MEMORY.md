# Memory Index

## The Person
- [rohit.md](rohit.md) — who Rohit is, how he works, what matters to him
- [homelab-infrastructure.md](homelab-infrastructure.md) — the homelab stack
- [hermes-architecture.md](hermes-architecture.md) — Hermes agent architecture and state
- [vision.md](vision.md) — what Rohit wants to build

## The Collaborator
- [relay.md](relay.md) — who Relay is
- [grants.md](grants.md) — standing permissions → ../grants.md
- [tempo.md](tempo.md) — calibration data → ../tempo.md
- [seedline.md](seedline.md) — version vector → ../seedline.md
- [ideas.md](ideas.md) — current ideas → ../ideas.md

## The Homelab's Backend Stores
- [databases.md](databases.md) — index of all 17+ DBs, what each contains, and how to query them
- [benchmarks/](benchmarks/) — canonical LLM benchmark store (tok/s, tool-call latency, load times), versioned; add runs via `bin/bench_llm.py`

## Decisions
- [minipc.md](minipc.md) — mini-PC augment purchase decision (recommendation: BOSGAME M6 $969)
- [ram-upgrade.md](ram-upgrade.md) — home-hp 32GB→64GB RAM decision (recommendation: Rimlance 32GB $158 Newegg)

## How to read this memory

This repo is the **thin index layer** — human-readable context and cross-tool continuity.
For detailed data (chat history, facts, narratives, capsule outcomes, preferences),
query the canonical backend stores listed in [databases.md](databases.md).

Loaded at session start during initialization. Sync first, then read this index.


## Career-Ops Automation
`projects/career-ops/` — batch career-run automation. Google Sheets `Jobs` tab is
the queue; n8n polls every 15m → bridge `/run` at `172.18.0.1:9199` (docker-bridge
only, LAN-locked) → `career_launch.sh` → `auto_pipeline.py` (deterministic ATS
keyword coverage via `_compute_ats_keyword_match`) → results written back to the
sheet row + posted to Telegram topic 7338, recorded in
`career_batch_results.tsv`. Phone trigger: paste a job URL or `/job <url>` in
topic 7338 → `career_ops_pipeline` Hermes plugin SSH-executes `auto_pipeline.py`
on the host. (Two triggers, separate dedup — avoid submitting the same URL both
ways.) Bridge service: `n8n-bridge.service` (ExecStart=/usr/bin/python3,
N8N_BRIDGE_HOST=172.18.0.1).

### 2026-08-30: bridge auth + Jarvis memory persistence

- **Bearer gate (defense-in-depth):** `/run`, `/cmd`, `/docker-*`, `/service-*`,
  `/run-cron` are now **bearer-mandatory** even from trusted/private IPs
  (`SENSITIVE_PATHS` in `n8n_bridge_server.py`). n8n workflow `/run` nodes send
  `Authorization: Bearer {{ $vars.BRIDGE_AUTH_KEY }}` (n8n project var; NOT hard-coded
  in the committed JSON). **n8n won't run until you create the n8n project variable
  `BRIDGE_AUTH_KEY` = `d6cbba9e9e3f09dcfb545c7ae0521ba5191407a7bb0bfcc401eeba1753001549`**
  (matches the unit env). Telegram `/run` routes in-process (`_call` → `HANDLERS`),
  unaffected. Verified: no-bearer `/run`=401, with-bearer=200.
- **Jarvis → Hermes memory persistence:** new bridge `/memory-write` (trust-gated,
  bind to docker bridge; runs `unified_memory.py store` as root via `sudo -n` with
  `HOME=/home/rohit`), and `openjarvis/tools.py` `_persist_reply()` POSTs each
  Jarvis reply to it. GateWay restart needed: `docker restart hermes` (s6-supervised).
  `hermes tools list` confirms `✓ openjarvis 🔌`. Jarvis runs `jarvis serve`
  @127.0.0.1:1377.
- **⚠️ OWNERSHIP MODEL (critical):** the hermes container (`stage2-hook.sh`) chowns
  the entire host `/home/rohit/.hermes` tree to uid **10000 mode 700** on every boot,
  which blocks the rohit-run bridge. Mitigations applied:
  - `plugins/`, `platforms/`, `.local/state/hermes`, `kanban*`, `kanban/` → uid 10000
    (gateway-owned). `data/unified_memory.db` + `data/career_batch_results.tsv` stay
    `rohit` (rohit-writable; memory-write uses `sudo -n` root so DB ownership is moot).
  - `n8n-bridge.service` now has `ExecStartPre=/usr/bin/sudo -n chmod 705
    /home/rohit/.hermes` (re-grants rohit traverse after container chowns) and
    `EnvironmentFile=/home/rohit/.relay/bridge.env` (copy of `.hermes/.env` — the
    container chowns `.env` to 10000:600 so the bridge reads the relocated copy).
  - If kanban fails after a container restart: re-chown `kanban.db*` files to 10000
    and remove stale 0-byte `-wal`/`-shm`.
  - **Do NOT restart the hermes container casually**: each boot re-chowns `.hermes`
    to 10000:700; the bridge's ExecStartPre self-heals on its next start, but other
    rohit-accessed files may need re-chowning.

### 2026-08-30 (late): n8n removed; Traefik repaired; Tailscale Funnel external access

- **n8n fully REMOVED** — it was unused (0 active workflows, 0 webhooks, 1 no-op test
  exec; the 3 "Chaguli" workflows lived in a STALE dir `/home/rohit/services/data/n8n/`
  NOT the live container volume `compose_n8n_data`). Removed from `apps.yml`
  (service block + `n8n_data` volume), container+volume+image deleted, Traefik
  `dynamic/n8n.yml` moved to `.removed-20260830`, 3 N8N_* lines removed from `.env`.
  The n8n-initiated career batch automation was never used (Telegram `/job` plugin
  remains the active career-ops path). Backups: `apps.yml.bak-remove-n8n-20260830`.
- **Traefik repairing** — it was DOWN (no container) and its file-provider dynamic
  routers pointed at STALE IPs from the previous proxy (e.g. immich=172.23.0.14,
  bookstack=172.23.0.3, portainer=172.23.0.12 → none existed). Traefik now runs
  (v2.11, `traefik/docker-compose.yml`, stack project `traefik`, network `traefik`).
  Rebuilt routing by **service name**: attached bookstack/healthchecks/immich_server/
  linkwarden/paperless/searxng to the `traefik` network (added to `apps.yml`
  `networks:`; NOTE these must each list `traefik`) and rewrote the dynamic routers
  to `http://<container>:<internal_port>` (bookstack:80, healthchecks:8000,
  immich_server:2283, linkwarden:3000, paperless:8000, searxng:8118). home-hp
  LAN/loopback reachability verified (bookstack 302, homepage/immich 200). *Pihole*
  stays on LAN-IP backend (rohit stack, host-net; already reachable).
- **Tailscale Funnel (public HTTPS)** — exposed via Traefik, URL
  **`https://home-hp.tail8f4175.ts.net:8443/{searxng,bookstack,healthchecks}`**.
  Path-routed (stripPrefix for searxng/bookstack; healthchecks keeps its prefix via
  SITE_ROOT). Traefik `funnel` entrypoint `:8888` (loopback publish) +
  `dynamic/funnel-routes.yml`. Apps base-URLs updated: healthchecks `SITE_ROOT`,
  bookstack `APP_URL`, searxng `settings.yml base_url` (all
  `https://home-hp.tail8f4175.ts.net:8443/...`). Started via
  `sudo tailscale funnel --bg --https=8443 http://127.0.0.1:8888` (operator not set;
  MUST use sudo). Config persists in tailscaled state. Funnel+HTTPS caps already
  enabled in tailnet (ports 443,8443,10000). Verified from this Mac over public
  URL (valid cert, bookstack 302, searxng 200, healthchecks 200).
- DuckDNS public IP (73.239.85.189) is NOT reachable from outside (no port-forward/
  tunnel) — Funnel replaces that path for 3 services; other duckdns hosts remain
  internal-only for now. Traefik ACME (duckdns challenge) still configured but certs
  not yet issued (no external request) — fine while Funnel fronts TLS.

### 2026-08-30 (very late): moved to TAILNET-ONLY access (Funnel removed)

- **Security decision**: user wants ALL services reachable only from their own
  tailnet devices (Mac, iPhone, Pixel) from anywhere — NOTHING public. Removed
  the public Tailscale Funnel entirely (was exposing searxng/bookstack/healthchecks
  at https://home-hp.tail8f4175.ts.net:8443/..., which are now all dead: 000 from
  outside). searxng was the real hole (no login). Posture: everything binds the
  **tailnet IP 100.122.58.40:<port>** (plus loopback) so Mac/iPhone reach it from
  any network via WireGuard mesh; NOT bound to 0.0.0.0 so it's not public.
- **Architecture**: NO port-forwarding (user declined); tailnet IS the access layer.
  Webhook-style public exposure (DuckDNS 73.239.85.189, its port-forward, and
  Traefik ACME duckdns certs) are NOT used. Traefik still runs for LAN-internal
  hostname routing + dashboard, but the `funnel` entrypoint (`:8888`) and
  `dynamic/funnel-routes.yml` were REMOVED (Traefik now only listens 80/443).
- **Tailnet port map (host pub -> container internal), all dual-bound 127.0.0.1 +
  100.122.58.40**:
  searxng :8118; healthchecks :8004->8000; bookstack :6875->80; paperless :8000;
  homepage :3003->3000; vaultwarden :8443->80; linkwarden :3011->3000;
  immich :2283; authentik-server :9001->9000. (ollama still loopback-only, standalone
  `docker run` not in compose; pihole binds 0.0.0.0 for DNS on LAN.)
- **Per-app URL envs pointed at tailnet URLs**: bookstack APP_URL, healthchecks
  SITE_ROOT, paperless PAPERLESS_URL, linkwarden NEXTAUTH_URL = http://100.122.58.40:<port>;
  vaultwarden DOMAIN = http://100.122.58.40:8443. immich IMMICH_SERVER_URL =
  http://100.122.58.40:2283.
- **iPhone access**: give each app its server URL as `http://100.122.58.40:<port>`
  (Immich: `http://100.122.58.40:2283`). Works over home WiFi and cellular.
- Verified from Mac (over DERP, outside home): searxng 200, healthchecks 302,
  bookstack 302, paperless 302, homepage 200, vaultwarden 200, linkwarden 200,
  immich 200; all 3 old Funnel URLs => 000 (down).
- Backups made: apps.yml.bak-tailnet-all-20260830, traefik.yml.bak-funnel-removal-*,
  docker-compose.yml.bak-funnel-removal-*.

### 2026-08-30 (tailnet session contd): authentik SSO pointed at tailnet URL
- Added `AUTHENTIK_URL: http://100.122.58.40:9001` to the authentik-server env
  block ONLY (NOT authentik-worker, whose identical env block caused an anchor
  duplicate; disambiguated by anchoring on `command: server` + tailnet ports).
- Verified: AUTHENTIK_URL present at runtime, server healthy, / -> 302 to
  http://100.122.58.40:9001/flows/-/default/authentication/ (200 follow). Login
  flow now resolves to tailnet so phone SSO works. authentik still binds
  127.0.0.1:9001 + 100.122.58.40:9001 (not public).
- Default fallback AUTHENTIK_SECRET_KEY is still 'changeme-replace-in-env' unless
  set in .env — should set a real secret if authentik is used for prod SSO.
- Backups: apps.yml.bak-authentik-url-20260830.

### 2026-08-30 (tailnet session contd): authentik secret + DB password secured
- Generated strong secrets and set in compose/.env: AUTHENTIK_SECRET_KEY
  (64-char urlsafe) + AUTHENTIK_DB_PASSWORD (43-char). .env stays 0600.
- Also ran ALTER USER authentik PASSWORD on the LIVE postgres DB (postgres only
  honors POSTGRES_PASSWORD on first init, so env change alone was not enough),
  then force-recreated authentik-server + authentik-worker with the new creds.
- Verified: both healthy, login flow reachable on tailnet 100.122.58.40:9001
  (302->200), works from Mac/outside.
- NOTE: changing AUTHENTIK_SECRET_KEY invalidates existing authentik sessions;
  users must re-login. Expected/correct for security hardening.
- Backups: .env.bak-authentik-secret-20260830, apps.yml.bak-authentik-url-20260830.
