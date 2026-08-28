---
created: 2026-08-28
confidence: high
source: hands-on restore
---

# PiHole Restored (2026-08-28)

## Summary
PiHole was found absent from the homelab — only a dead `nameserver 127.0.0.1`
entry pointed at nothing, and host DNS fell back to 1.1.1.1. Full config and
data were recovered from backups and the container redeployed.

## What was recovered
1. **Compose definition** — `/home/rohit/AgentChaguli/services/docker/compose/core.yml`
   (image `pihole/pihole:2026.04.1`).
2. **Docker container runtime config** — from
   `/mnt/usb/backups/agentharness-backups/2026-06-15/docker/container_inspect.json`
   (ports 53/53/8053, volumes, caps, env; WEBPASSWORD was empty '').
3. **/etc/pihole data volume** — from
   `/mnt/usb/backups/docker-volumes/2026-06-15/pihole.tar.gz`:
   - pihole.toml (v6.6.1) — blocking active NULL mode, web port 8053,
     upstreams **8.8.8.8 / 8.8.4.4 / 1.1.1.1**, API pwhash preserved
   - gravity.db — **298,974 blocked domains**, 9 adlists, 5 custom domain rules
   - custom.list — ~50 local DNS overrides (all *.home, *.chagulihome.duckdns.org → 192.168.29.10)
   - pihole-FTL.db query history

## Deploy action
Added `pihole` service + `volumes:` top-level to `/home/rohit/docker-compose.yml`
(was only hermes gateway+dashboard, all host-network). PiHole uses bridge
networking with published ports 53/tcp, 53/udp, 8053. Volumes mark
`pihole_pihole_data` / `pihole_pihole_dnsmasq` external. Backup of compose
before edit: `docker-compose.yml.bak-pihole`.

## Verified working
- `dig @127.0.0.1 google.com` → resolves (host resolv.conf already points at
  127.0.0.1:53, now live via PiHole)
- Local override `hermes.home` → 192.168.29.10
- Ad block `doubleclick.net` → 0.0.0.0 (blocking active)
- LAN reachable: `dig @192.168.29.10 google.com` resolves
- Web admin `http://127.0.0.1:8053/admin/` → 302 (login)
- Hermes unaffected (12h uptime after change)

## Notes
- PiHole binds 0.0.0.0:53 so the host + LAN clients on 192.168.29.10 can use it
  as network DNS (set via router DHCP if network-wide blocking desired).
- Traefik not currently running, but `/home/rohit/services/traefik/dynamic/pihole.yml`
  still routes `pihole.chagulihome.duckdns.org` → 192.168.29.10:8053 and will
  apply when the traefik stack is up.
- `PIHOLE_WEBPASSWORD` is empty; the real password is the preserved API pwhash
  in pihole.toml.
