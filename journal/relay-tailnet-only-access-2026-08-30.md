# Relay session — 2026-08-30 (very late): tailnet-only access, Funnel removed

## Ask (after earlier session secured Funnel for 3 services)
User wants all services reachable from their own tailnet devices (Mac, iPhone,
Pixel) from ANYWHERE (home WiFi or outside) — and NOTHING exposed publicly.
They explicitly declined port-forwarding. When asked about searxng (the only
public endpoint with no login), user said "make everything like immich, nothing
exposed to public."

## What changed
1. **Funnel off**: `sudo tailscale funnel --bg --https=8443 off` -> "No serve config".
   All 3 public URLs now return 000 from outside. (Correct off syntax is
   `tailscale funnel off` / `--bg --https=<port> off`, NOT bare `--https=<port>`.)
2. **Tailnet bindings**: patched `apps.yml` to dual-bind every service to the
   tailnet IP 100.122.58.40:<port> (plus keep loopback). Recreated each container.
   Traps hit:
   - Composing over SSH with single-quoted python heredocs breaks zsh (`unmatched '`).
     Fix: write patch file locally, `scp` to host, run `sudo python3 /tmp/x.py`.
   - `docker compose up -d` in the working dir without `-f apps.yml -p compose`
     reported "no such service" and `ps` was empty -> must always use
     `-f apps.yml -p compose`.
   - Batch `up -d --no-deps a b c...` aborted on the FIRST name conflict (ollama)
     and did NOT recreate the rest. Fix: loop per-service with
     `up -d --force-recreate --no-deps <svc>`.
   - ollama is NOT owned by compose (no project labels) — standalone `docker run`.
     apps.yml edit for it is inert; left loopback-only (API, no UI, fine).
3. **Traefik cleanup**: removed `funnel` entrypoint from traefik.yml + deleted
   `dynamic/funnel-routes.yml` (moved to .removed-20260830-tailnet) + removed the
   `127.0.0.1:8888:8888` publish; recreated Traefik. Now listens only 80/443.
   (Traps: my `for` loop over python string variants to remove the 8888 line matched
   NOTHING but also deleted nothing — verified 80/443 intact; removed line 9 exactly.)
4. **Per-app URL envs** now point at tailnet URLs (APP_URL/SITE_ROOT/PAPERLESS_URL/
   NEXTAUTH_URL/DOMAIN = http://100.122.58.40:<port>), so deep links resolve.

## End state (verified from Mac over DERP, outside home network)
- Public Funnel: DOWN (000) — nothing public.
- Tailnet reachable: searxng 200, healthchecks 302, bookstack 302, paperless 302,
  homepage 200, vaultwarden 200, linkwarden 200, immich 200.
- Mac/laptop already on tailnet => all reachable from anywhere, no config.
- iPhone/Pixel: set each app server URL to http://100.122.58.40:<port>.

## Residual notes
- pihole binds 0.0.0.0:53/8053 (LAN DNS + admin on LAN) — not tailnet-bound, fine,
  not public (no port-forward).
- authentik-server bound to tailnet :9001 as SSO; NEXTAUTH/authentik redirect URLs
  not yet fully pointed at tailnet (only core apps done). Could revisit.
- Traefik web/websecure bind 0.0.0.0:80/443 (LAN + tailnet interfaces) but only match
  specific Host headers -> hitting the IP directly 404s. Not a practical hole, but
  if strict tailnet-only cleanliness wanted, bind Traefik to 127.0.0.1 or 100.122.58.40.