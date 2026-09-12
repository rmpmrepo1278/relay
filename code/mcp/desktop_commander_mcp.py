#!/usr/bin/env python3
"""MCP wrapper for DesktopCommanderMCP - terminal + filesystem tools."""
import json
import subprocess
import sys
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
DESKTOP_MCP_PATH = Path("/tmp/DesktopCommanderMCP/dist/index.js")


def list_tools():
    """List available tools from DesktopCommanderMCP."""
    try:
        result = subprocess.run(
            ["node", str(DESKTOP_MCP_PATH), "--list-tools"],
            capture_output=True, text=True, timeout=10
        )
        return json.loads(result.stdout) if result.stdout else []
    except Exception as e:
        return [{"error": str(e)}]


def run_tool(tool_name: str, args: dict):
    """Run a tool via DesktopCommanderMCP."""
    try:
        payload = json.dumps({"name": tool_name, "arguments": args})
        result = subprocess.run(
            ["node", str(DESKTOP_MCP_PATH)],
            input=payload, capture_output=True, text=True, timeout=30
        )
        return json.loads(result.stdout) if result.stdout else {}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    if "--list" in sys.argv:
        print(json.dumps(list_tools(), indent=2))
    elif len(sys.argv) > 2:
        print(json.dumps(run_tool(sys.argv[1], json.loads(sys.argv[2])), indent=2))
    else:
        print("Usage: desktop_commander_mcp.py --list")
        print("       desktop_commander_mcp.py <tool> <json_args>")
