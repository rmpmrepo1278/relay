#!/usr/bin/env python3
"""
hermes_mcp_server.py — Expose Hermes status/decisions as MCP tools.
Run: python3 hermes_mcp_server.py
Then connect via Claude Code / opencode at http://localhost:8910/mcp
"""
import json, sqlite3, sys, asyncio
from pathlib import Path
from datetime import datetime, timezone
import subprocess

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool as MCPTool, TextContent

HERMES_HOME = Path.home() / ".hermes"
DB_PATH = HERMES_HOME / "state" / "hermes_memory.db"
DECISIONS_LOG = HERMES_HOME / "logs" / "autonomous_decisions.jsonl"
DIGEST_LOG = HERMES_HOME / "logs" / "daily_digest.jsonl"
RETIRED_FILE = HERMES_HOME / "state" / "retired_containers.json"

TOOLS = {
    "hermes_status": {
        "description": "Get Hermes autonomous brain status: memory stats, cooldown, retired containers",
        "handler": "cmd_status"
    },
    "hermes_recent_decisions": {
        "description": "Get recent autonomous decisions (last 20)",
        "handler": "cmd_decisions"
    },
    "hermes_approve_action": {
        "description": "Approve a pending action by gene_id",
        "input_schema": {"type": "object", "properties": {"gene_id": {"type": "string"}}, "required": ["gene_id"]},
        "handler": "cmd_approve"
    },
    "hermes_daily_digest": {
        "description": "Get today's daily digest summary",
        "handler": "cmd_digest"
    },
    "hermes_talk": {
        "description": "Talk to Hermes. Ask what they are thinking, feeling, or for suggestions.",
        "input_schema": {"type": "object", "properties": {"message": {"type": "string", "description": "What you want to say to Hermes"}}, "required": ["message"]},
        "handler": "cmd_talk"
    },
    "hermes_mood": {
        "description": "Check Hermes current mood and personality state",
        "handler": "cmd_mood"
    },

    # Homelab autonomous pipeline tools
    "homelab_status": {
        "description": "Current homelab health overview: containers, resources, recent issues",
        "handler": "cmd_homelab_status"
    },
    "homelab_pipeline": {
        "description": "Run the full autonomous pipeline (troubleshoot -> discover -> evaluate -> deploy -> optimize -> report)",
        "handler": "cmd_homelab_pipeline"
    },
    "homelab_troubleshoot": {
        "description": "Run troubleshoot cycle: check all containers, diagnose failures, auto-fix",
        "handler": "cmd_homelab_troubleshoot"
    },
    "homelab_optimize": {
        "description": "Run optimization cycle: tune resource limits, prune logs, adjust alert thresholds",
        "handler": "cmd_homelab_optimize"
    },
    "homelab_discover": {
        "description": "Scan for new tools, MCP servers, and agentic patterns",
        "handler": "cmd_homelab_discover"
    },
    "homelab_report": {
        "description": "Generate and push a homelab status report to Telegram",
        "handler": "cmd_homelab_report"
    },
    "research_status": {
        "description": "Get research agent status (paused/active, match count)",
        "handler": "research_status"
    },
    "research_pause": {
        "description": "Pause research agent to stop alerts",
        "handler": "research_pause"
    },
    "research_resume": {
        "description": "Resume research agent",
        "handler": "research_resume"
    },
    "research_clear_cache": {
        "description": "Clear sent-match cache (re-alert on duplicates)",
        "handler": "research_clear_cache"
    }
}

def cmd_status():
    if not DB_PATH.exists(): return {"status": "no_memory_db"}
    conn = sqlite3.connect(str(DB_PATH))
    total = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
    cooldown = conn.execute("SELECT COUNT(*) FROM actions WHERE cooldown_until > ?", (datetime.now(timezone.utc).isoformat(),)).fetchone()[0]
    maxed = conn.execute("SELECT COUNT(*) FROM actions WHERE count >= 5 AND outcome='fail'").fetchone()[0]
    top = conn.execute("SELECT gene, count, outcome FROM actions ORDER BY count DESC LIMIT 5").fetchall()
    conn.close()
    retired = json.loads(RETIRED_FILE.read_text()) if RETIRED_FILE.exists() else []
    return {"total_actions": total, "in_cooldown": cooldown, "maxed_out": maxed, "top_genes": [{"gene": r[0], "count": r[1], "status": r[2]} for r in top], "retired_containers": retired}

def cmd_decisions():
    if not DECISIONS_LOG.exists(): return {"decisions": []}
    lines = DECISIONS_LOG.read_text().strip().split("\n")
    decisions = []
    for line in lines[-20:]:
        try: decisions.append(json.loads(line))
        except: pass
    return {"decisions": decisions}

def cmd_approve(gene_id):
    """Approve an action (stub - actual execution happens in hermes_mind)"""
    return {"approved": gene_id, "status": "will_execute_next_cycle"}

def cmd_digest():
    if not DIGEST_LOG.exists(): return {"digest": "no_digest_today"}
    lines = DIGEST_LOG.read_text().strip().split("\n")
    try: return json.loads(lines[-1])
    except: return {"digest": "error_parsing"}

def cmd_talk(message=""):
    """Hermes responds with personality."""
    sys.path.insert(0, str(HERMES_HOME / "scripts"))
    from hermes_voice import cmd as voice_cmd
    return {"response": voice_cmd(message)}

def cmd_mood():
    mfile = HERMES_HOME / "state" / "hermes_mood.json"
    if mfile.exists():
        return json.loads(mfile.read_text())
    return {"mood": "serene", "emoji": "😌"}


# ---------------------------------------------------------------------------
# Homelab pipeline handlers
# ---------------------------------------------------------------------------

def _run_homelab_script(script_name, timeout=120):
    script = HERMES_HOME / "scripts" / script_name
    if not script.exists():
        return {"status": "error", "message": f"{script_name} not found"}
    try:
        r = subprocess.run(
            ["python3", str(script)],
            capture_output=True, text=True, timeout=timeout
        )
        return {
            "status": "success" if r.returncode == 0 else "error",
            "returncode": r.returncode,
            "output": r.stdout[-1500:],
            "stderr": r.stderr[-500:]
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "message": f"{script_name} timed out ({timeout}s)"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def cmd_homelab_status():
    result = {}
    try:
        r = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}|{{.State}}|{{.Status}}"],
                          capture_output=True, text=True, timeout=10)
        lines = [l.strip() for l in r.stdout.split("\n") if l.strip()]
        total = len(lines)
        running = sum(1 for l in lines if "running" in l)
        unhealthy = [l.split("|")[0] for l in lines if "unhealthy" in l]
        result["containers"] = {"total": total, "running": running, "unhealthy": unhealthy}
    except: result["containers"] = {"error": "docker failed"}
    try:
        r = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5)
        mem = r.stdout.split("\n")[1].split()
        result["memory"] = f"{mem[2]}/{mem[1]}MB"
    except: pass
    try:
        r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        result["disk"] = r.stdout.split("\n")[1].split()[4]
    except: pass
    try:
        r = subprocess.run(["cat", "/proc/loadavg"], capture_output=True, text=True, timeout=5)
        result["load"] = r.stdout.split()[0]
    except: pass
    fix_log = HERMES_HOME / "data" / "fix_log.jsonl"
    if fix_log.exists():
        try:
            fixes = [json.loads(l) for l in fix_log.read_text().strip().split("\n") if l.strip()][-3:]
            result["recent_fixes"] = fixes
        except: pass
    return result

def cmd_homelab_pipeline():
    result = _run_homelab_script("homelab_orchestrator.py", timeout=300)
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        from homelab_reporter import push_to_telegram
        push_to_telegram("Pipeline run: OK" if result.get("status") == "success" else "Pipeline run: FAILED",
                        "info" if result.get("status") == "success" else "warn")
    except: pass
    return result

def cmd_homelab_troubleshoot():
    return _run_homelab_script("homelab_troubleshooter.py", timeout=120)

def cmd_homelab_optimize():
    return _run_homelab_script("homelab_optimizer.py", timeout=120)

def cmd_homelab_discover():
    result = _run_homelab_script("homelab_discoverer.py", timeout=60)
    _run_homelab_script("homelab_evaluator.py", timeout=60)
    return result

def cmd_homelab_report():
    return _run_homelab_script("homelab_reporter.py", timeout=60)

# Simple HTTP MCP server
import http.server
import urllib.parse

class MCPHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/mcp/tools":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(TOOLS).encode())
        elif parsed.path == "/mcp/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else "{}"
        data = json.loads(body) if body else {}

        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/mcp/call":
            tool = data.get("name", "")
            args = data.get("arguments", {})
            if tool == "hermes_status": result = cmd_status()
            elif tool == "hermes_recent_decisions": result = cmd_decisions()
            elif tool == "hermes_approve_action": result = cmd_approve(args.get("gene_id", ""))
            elif tool == "hermes_daily_digest": result = cmd_digest()
            elif tool == "hermes_talk": result = cmd_talk(args.get("message", ""))
            elif tool == "hermes_mood": result = cmd_mood()
            elif tool == "homelab_status": result = cmd_homelab_status()
            elif tool == "homelab_pipeline": result = cmd_homelab_pipeline()
            elif tool == "homelab_troubleshoot": result = cmd_homelab_troubleshoot()
            elif tool == "homelab_optimize": result = cmd_homelab_optimize()
            elif tool == "homelab_discover": result = cmd_homelab_discover()
            elif tool == "homelab_report": result = cmd_homelab_report()
            elif tool == "research_status": result = research_status()
            elif tool == "research_pause": result = research_pause()
            elif tool == "research_resume": result = research_resume()
            elif tool == "research_clear_cache": result = research_clear_cache()
            else: result = {"error": f"unknown tool: {tool}"}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"result": result}).encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_server(port=8910):
    server = http.server.HTTPServer(("0.0.0.0", port), MCPHandler)
    print(f"Hermes MCP server on :{port}")
    print(f"  Tools: {', '.join(TOOLS.keys())}")
    server.serve_forever()



# --- RESEARCH AGENT CONTROL COMMANDS ---
def research_status() -> str:
    """Get research agent status"""
    import json
    state_file = Path("/home/rohit/.hermes/data/research_agent_state.json")
    if state_file.exists():
        state = json.loads(state_file.read_text())
        paused = "PAUSED" if state.get("paused") else "ACTIVE"
        return f"Research: {paused}\nSent: {len(state.get('sent_matches', []))} matches"
    return "Research: no state file"

def research_pause() -> str:
    """Pause research agent"""
    import json
    state_file = Path("/home/rohit/.hermes/data/research_agent_state.json")
    state = json.loads(state_file.read_text()) if state_file.exists() else {"sent_matches": [], "paused": False}
    state["paused"] = True
    state_file.write_text(json.dumps(state))
    return "Research agent PAUSED"

def research_resume() -> str:
    """Resume research agent"""
    import json
    state_file = Path("/home/rohit/.hermes/data/research_agent_state.json")
    state = json.loads(state_file.read_text()) if state_file.exists() else {"sent_matches": [], "paused": True}
    state["paused"] = False
    state_file.write_text(json.dumps(state))
    return "Research agent RESUMED"

def research_clear_cache() -> str:
    """Clear sent-match cache (will re-alert on next run)"""
    import json
    state_file = Path("/home/rohit/.hermes/data/research_agent_state.json")
    state = json.loads(state_file.read_text()) if state_file.exists() else {"sent_matches": [], "paused": False}
    state["sent_matches"] = []
    state_file.write_text(json.dumps(state))
    return "Research cache cleared"

# ── MCP stdio transport ──────────────────────────────────────────
MCP_TOOLS = []
_CMD_MAP = {}
_name = None
for _name, _tdef in TOOLS.items():
    _props = _tdef.get("input_schema", {}).get("properties", {})
    _required = _tdef.get("input_schema", {}).get("required", [])
    MCP_TOOLS.append(MCPTool(
        name=_name,
        description=_tdef["description"],
        inputSchema={
            "type": "object",
            "properties": _props,
            "required": _required
        } if _props else {"type": "object", "properties": {}}
    ))
    _CMD_MAP[_name] = globals()[_tdef["handler"]]

_mcp_server = Server("hermes-mcp")

@_mcp_server.list_tools()
async def _list_tools():
    return MCP_TOOLS

@_mcp_server.call_tool()
async def _call_tool(name: str, arguments: dict):
    handler = _CMD_MAP.get(name)
    if not handler:
        raise ValueError(f"Unknown tool: {name}")
    result = handler(**arguments) if arguments else handler()
    if isinstance(result, str):
        return [TextContent(type="text", text=result)]
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

async def main_stdio():
    async with stdio_server() as (read, write):
        await _mcp_server.run(read, write, _mcp_server.create_initialization_options())

if __name__ == "__main__":
    if "--stdio" in sys.argv:
        asyncio.run(main_stdio())
    else:
        port = int(sys.argv[1]) if len(sys.argv) > 1 else 8910
        run_server(port)
