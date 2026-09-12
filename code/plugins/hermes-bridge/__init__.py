# ── Hermes Bridge plugin ────────────────────────────────────────────────
# Exposes homelab capabilities as slash commands in Telegram (and CLI).
# Routes every command to the n8n host bridge's /cmd endpoint on 127.0.0.1:9199.
# The bridge handles the actual execution (docker, code-graph, briefings...).
import json
import os
import urllib.request

BRIDGE_URL = os.environ.get("HERMES_BRIDGE_URL", "http://127.0.0.1:9199/cmd")
BRIDGE_AUTH = os.environ.get("BRIDGE_AUTH_KEY", "default-key-change-me")
TIMEOUT = 120


def _call_bridge(text: str) -> str:
    """POST a command to the bridge /cmd endpoint and return display text."""
    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        BRIDGE_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + BRIDGE_AUTH,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return f"⚠️ Bridge error: {e}"
    result = data.get("result", data)
    if isinstance(result, dict):
        return result.get("text") or result.get("error") or json.dumps(result)
    return str(result)


_COMMAND_DEFS = {
    "hhelp": ("", "List all Hermes commands"),
    "hstatus": ("", "Hermes service health"),
    "hhealth": ("", "Bridge ping check"),
    "hdocker": ("", "Running containers"),
    "hrestart": ("<container>", "Restart a container"),
    "hlogs": ("<container> [lines]", "Container logs"),
    "hdisk": ("", "Disk usage"),
    "hbackup": ("", "Backup status"),
    "hmetrics": ("", "CPU/memory snapshot"),
    "hgraph": ("", "Code graph status"),
    "hdeadcode": ("", "Dead code report"),
    "harch": ("", "Code graph architecture"),
    "hsearch": ("<query>", "Search code graph"),
    "himpact": ("<files>", "Impact of file changes"),
    "hbriefing": ("", "Morning briefing"),
    "halert": ("", "Unhealthy containers"),
     "hsched": ("", "Scheduler state"),
     "hrun": ("<cmd>", "Run a shell command"),
     "hledger": ("[stats|recent]", "Decision ledger"),
     "hcommitments": ("[status|overdue]", "Active commitments"),
     "hqueue": ("", "Task queue"),
     "hdigest": ("", "Daily digest"),
     "hdoctor": ("", "Run system doctor"),
     "hmemory": ("<query>", "Search unified memory"),
     "hproactive": ("", "Proactive engine state"),
     "hcap": ("", "Provider caps"),
     "hcost": ("", "Cost guard status"),
     "hrouting": ("[status|enable <name>|disable <name>|reset]", "Provider routing"),
    "hesclate": ("", "Human escalation stats"),
    "hgraphify": ("<cmd>", "Graphify AST search (path, explain, diagnose)"),
    "hgraphify-path": ("<node-a> <node-b>", "Shortest path between two nodes"),
    "hgraphify-explain": ("<node-name>", "Explain a node and its neighbors"),
 }


_BRIDGE_MAP = {
    "hhelp": "/help",
    "hstatus": "/status",
    "hhealth": "/health",
    "hdocker": "/docker",
    "hrestart": "/restart",
    "hlogs": "/logs",
    "hdisk": "/disk",
    "hbackup": "/backup",
    "hmetrics": "/metrics",
    "hgraph": "/graph",
    "hdeadcode": "/deadcode",
    "harch": "/arch",
    "hsearch": "/search",
    "himpact": "/impact",
    "hbriefing": "/briefing",
    "halert": "/alert",
     "hsched": "/scheduler",
     "hrun": "/run",
     "hledger": "/ledger",
     "hcommitments": "/commitments",
     "hqueue": "/queue",
     "hdigest": "/digest",
     "hdoctor": "/doctor",
     "hmemory": "/memory",
     "hproactive": "/proactive",
     "hcap": "/cap",
     "hcost": "/cost",
     "hrouting": "/routing",
     "hesclate": "/escalate",
    "hgraphify": "/graphify",
    "hgraphify-path": "/graphify-path",
    "hgraphify-explain": "/graphify-explain",
 }


_CONFIRM_REQUIRED = {"hrestart", "hrun", "hdoctor"}
_CONFIRM_MARKER = "confirm"


def _make_handler(name: str):
    def handler(raw_args: str) -> str:
        args = raw_args.strip()
        if name in _CONFIRM_REQUIRED:
            parts = args.split()
            if not parts:
                return (
                    f"⚠️ `{name}` needs an argument — send it again "
                    f"with `confirm` as the first word to execute."
                )
            if parts[0].lower() != _CONFIRM_MARKER:
                what = "this action"
                return (
                    f"⚠️ Confirm destructive action?\n\n"
                    f"To proceed, re-send the command with `confirm` first, e.g.:\n"
                    f"`{name} confirm {args}`"
                )
            args = " ".join(parts[1:])
        text = _BRIDGE_MAP[name] + (" " + args if args else "")
        return _call_bridge(text)
        return _call_bridge(text)

    return handler


def register(ctx) -> None:
    for name, (args_hint, description) in _COMMAND_DEFS.items():
        ctx.register_command(
            name,
            handler=_make_handler(name),
            description=description,
            args_hint=args_hint,
        )
