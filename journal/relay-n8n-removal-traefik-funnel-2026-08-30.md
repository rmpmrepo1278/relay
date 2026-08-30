# Relay session — 2026-08-30 (late): n8n removal, Traefik repair, Tailscale Funnel

## Ask
Fully remove n8n (unused), clean up .env, fix Traefik ("it replaced the previous
reverse proxy"), then restore external access — user chose Tailscale Funnel.

## n8n removal
- Proved unused first: live container DB (`/var/lib/docker/volumes/compose_n8n_data/
  _data/database.sqlite`) had **1 workflow (Career-Ops), active=0, 0 webhooks,
  1 manual no-op exec**. The 3 "Chaguli" workflows were in a STALE host dir
  `/home/rohit/services/data/n8n/.n8n/database.sqlite` (April) — NOT the container's
  mount (compose volume). That stale dir is what earlier session work queried by
  mistake.
- Removed: compose `n8n:` service + `n8n_data` volume from apps.yml, container,
  volume, image, `traefik/dynamic/n8n.yml` → `.removed-20260830`, 3 N8N_* lines in
  `.env` flagged as stale creds. Backups: `apps.yml.bak-remove-n8n-20260830`.
- Conclusion: career ops runs via Telegram `/job` plugin (`career_ops_pipeline`
  pre_gateway_dispatch hook → `auto_pipeline.py` direct) — never needed n8n.

## Traefik repair
- WAS DOWN (no container) and file-provider routers pointed at stale IPs of the
  previous proxy. Brought up via `docker compose up -d` (project `traefik`).
- Rebuilt by service name: added `traefik` to networks for bookstack, healthchecks,
  immich_server, linkwarden, paperless, searxng in apps.yml; recreated them;
  rewrote dynamic routers `http://<container>:<port>`; verified from traefik
  container DNS + HTTPS (bookstack 302, homepage/immich 200).
- YAML gotcha: naive python append put `- traefik` on the same line as a network
  entry (`- paperless_default    - traefik`) → fixed by newline-split replace,
  compose re-validated.

## Tailscale Funnel
- Node caps already had funnel/https (`funnel-ports=443,8443,10000`) — no admin
  change needed. Tailscaled runs with serve config in state → persists reboots.
- Architecture: Funnel (8443) → Traefik `funnel` entrypoint `127.0.0.1:8888`
  (loopback publish) → path routers `/searxng /bookstack /healthchecks` with
  stripPrefix for searxng/bookstack (healthchecks keeps prefix; SITE_ROOT set).
- Apps base-URL envs set to `https://home-hp.tail8f4175.ts.net:8443/...`.
- Command (MUST BE SUDO, operator not set):
  `sudo tailscale funnel --bg --https=8443 http://127.0.0.1:8888`
- Verified from this Mac over public internet: valid TLS cert,
  /bookstack 302, /searxng 200, /healthchecks/docs 200.
- Lingering: DuckDNS (73.239.85.189) not externally reachable (no port-forward/
  tunnel) — other duckdns hosts internal-only; traefik ACME duckdns challenge
  unexercised. pihole router still LAN-IP (fine, separate host-net stack).

## Residual fragilities
- `docker compose up -d <svc>` with a full file recreate can renumber IPs; by-name
  routing immune. Removed-services test queries must target the compose `n8n` VOLUME
  path, not `/home/rohit/services/data/n8n` (stale).
- Traefik file provider reloads on watch; funnel-routes uses `funnel` entrypoint —
  adding more apps requires new PathPrefix router + strip config + the app's base-URL
  env, and the app container already joined the `traefik` network.
- Any `docker restart hermes` still re-chowns `.hermes` to 10000:700 (see earlier
  entry); bridge self-heals via ExecStartPre.