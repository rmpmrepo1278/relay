#!/usr/bin/env python3
"""
crg_context.py — Quick CRG context before any code work.

Usage:
  crgctx                      # context for ~/.hermes
  crgctx /path/to/repo        # for any registered repo

Dumps: repo stats, top communities, architecture overview, dead-code
candidates, and suggests which CRG MCP tool to call next.

This is the recommended FIRST STEP before any code reading or editing,
per the CRG-FIRST MANDATE in AGENTS.md.
"""
from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
REGISTERED = {
    "hermes": str(Path.home() / ".hermes" / "collaborator-memory"),
    "collaborator-memory": str(Path.home() / ".hermes" / "collaborator-memory"),
    "career-ops": str(Path.home() / "projects" / "career-ops"),
    "BigMoeOnEdge": str(Path.home() / "BigMoeOnEdge"),
}


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.stdout.strip() + (r.stderr.strip() if r.returncode != 0 else "")
    except Exception as e:
        return f"(error: {e})"


def _run_json(cmd: list[str]) -> dict | None:
    out = _run(cmd)
    # Try to parse JSON from output
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
    # Try parsing full output
    try:
        return json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return None


def resolve_repo(arg: str | None) -> str:
    """Resolve the repo path from argument."""
    if not arg:
        return str(HERMES_HOME)
    if arg in REGISTERED:
        return REGISTERED[arg]
    # Check if it's a path
    p = Path(arg).expanduser()
    if p.exists():
        return str(p)
    # Check if it's a directory name under ~
    candidate = Path.home() / arg
    if candidate.exists():
        return str(candidate)
    # Default
    return arg


def main():
    repo_arg = sys.argv[1] if len(sys.argv) > 1 else None
    repo_path = resolve_repo(repo_arg)

    print(f"🔍 CRG Context for: {repo_path}")
    print("=" * 60)

    # 1. Status
    status = _run(["code-review-graph", "status", "--repo", repo_path])
    if status:
        print("\n📊 Graph Stats:")
        for line in status.splitlines():
            if line.strip():
                print(f"  {line.strip()}")
    else:
        print("\n📊 Graph Stats: (not built — run: code-review-graph build)")

    # 2. Top communities (architecture)
    arch = _run_json(["code-review-graph", "architecture", "--repo", repo_path])
    if arch:
        print("\n🏛️ Architecture Overview:")
        comms = arch.get("communities", []) if isinstance(arch, dict) else []
        for c in comms[:5]:
            name = c.get("name", "unknown") if isinstance(c, dict) else str(c)
            size = c.get("size", 0) if isinstance(c, dict) else "?"
            print(f"  • {name} ({size} nodes)")
    else:
        # Fallback to text status
        arch_text = _run(["code-review-graph", "architecture", "--repo", repo_path])
        if arch_text:
            print("\n🏛️ Architecture:")
            for line in arch_text.splitlines()[:6]:
                print(f"  {line.strip()}")

    # 3. Dead code candidates
    dead = _run_json(["code-review-graph", "dead-code", "--repo", repo_path, "--limit", "8"])
    if dead and isinstance(dead, dict):
        items = dead.get("results", dead.get("nodes", dead.get("dead_code", [])))
        if items:
            print(f"\n💀 Top dead-code candidates ({len(items)}):")
            for item in items[:8]:
                name = item.get("name", "?") if isinstance(item, dict) else str(item)
                fpath = item.get("file_path", "") if isinstance(item, dict) else ""
                print(f"  • {name} @ {Path(fpath).name if fpath else '?'}")
        else:
            print("\n💀 Dead-code: none found (clean!)")
    elif dead:
        print(f"\n💀 Dead-code: {dead}")

    # 4. Suggested next tools
    print("\n💡 Suggested CRG MCP tools to call next:")
    print("  - semantic_search_nodes \"<query>\"     # Find by intent")
    print("  - query_graph callers_of <Function>      # Who calls this?")
    print("  - query_graph importers_of <Module>      # Who imports this?")
    print("  - get_impact_radius <file_or_func>       # Blast radius before edits")
    print("  - list_flows --sort-by criticality       # Main execution paths")
    print("  - detect_changes                         # Review pending changes")

    print("\n🚀 CRG-first: query the graph before reading files.")
    print("   (Save ~90% tokens vs grep/read — docs/CLAUDE.md mandate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
