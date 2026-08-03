# relay-telegram-access-2026-08-02.md

## Telegram accessibility for Hermes capabilities — DONE

Made Hermes homelab capabilities reachable from Telegram slash commands.

### What changed
1. **n8n bridge `/cmd` router** (`.hermes/scripts/n8n_bridge_server.py`):
   - Appended a Telegram command router: `@handler("/cmd")` + `_route_telegram_command()`.
   - Friendly commands: `/help /status /health /docker /restart /logs /disk /backup
     /metrics /graph /deadcode /arch /search /impact /briefing /alert /scheduler /run`.
   - Proxies onto existing bridge handlers (`/system-health`, `/docker-ps`, `/code-graph/*`, …).
   - Fixed pre-existing missing `from pathlib import Path` that broke morning/evening briefings.
   - `n8n-bridge.service` (systemd user) restarted; verified `/cmd` + all subcommands.
   - ⚠️ Gotcha: any appended code MUST go BEFORE the final `if __name__ == "__main__": main()`
     block, or it never runs (the router was appended after it initially — server stayed on
     the old handler set until the block was reordered).

2. **`hermes-bridge` plugin** (`.hermes/plugins/hermes-bridge/`, enabled in `config.yaml`):
   - Registers 18 Telegram slash commands with the `h` prefix to avoid built-in clashes:
     `/hhelp /hstatus /hhealth /hdocker /hrestart /hlogs /hdisk /hbackup /hmetrics
     /hgraph /hdeadcode /harch /hsearch /himpact /hbriefing /halert /hsched /hrun`.
   - Handler maps `h*` → bridge command (e.g. `hgraph` → `/graph`) and POSTs to
     `http://127.0.0.1:9199/cmd`, returns the text.
   - Verified each handler end-to-end via `get_plugin_command_handler()` (bridge on 9199).
   - Gateway restarted to pick up the new plugin + Telegram menu.

3. **Committed + pushed**: home repo `master` → `chaguli` (github rmpmrepo1278/AgentChaguli),
   commit `c7693f7`.

### Verified outputs
- `/graph` → 2432 nodes / 21865 edges / 271 files.
- `/briefing` → journal + scheduler (60708 runs, 6 failures) + career + containers.
- `/docker` → 34 containers; `/logs n8n 5` → tail; `/alert` → 0 unhealthy.
- `/hsearch telegram` → 20 nodes hybrid search results.

### Notes / follow-ups
- `/hbackup` returns "No backup report found" — `~/.hermes/backup_all_report.json` absent.
- Tailscale on Mac still logged out; homelab reachable via `homelab-lan` (192.168.29.10).
- Remaining from earlier task list: extracting user request history from opencode.db /
  Claude Code jsonl to map friction points. Deferred (not needed for the Telegram path).
