#!/usr/bin/env python3
"""
skill_library.py — Extract, index, and serve L1 remediation skills.

When the autonomous fixer successfully resolves an issue via L2 Claude,
this module extracts the concrete commands used into a reusable L1 bash
script. These scripts can then be applied directly by the fixer for
future occurrences of the same issue type + target, skipping the Claude
delegation entirely.

Usage:
  python3 skill_library.py extract          # Extract skills from recent successful L2 fixes
  python3 skill_library.py search "oom"     # Search skills by keyword
  python3 skill_library.py apply <skill>    # Run a skill
  python3 skill_library.py list             # List all skills
  python3 skill_library.py index            # Rebuild search index
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
SKILLS_DIR = HERMES_HOME / "skill_library"
INDEX_FILE = SKILLS_DIR / ".index.json"
REFLEXION_FILE = HERMES_HOME / "reflexion_memory.jsonl"


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] skill-library: {msg}"
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    with open(HERMES_HOME / "logs" / "skill_library.log", "a") as f:
        f.write(line + "\n")
    print(line, file=sys.stderr)


def load_reflexions() -> list[dict]:
    if not REFLEXION_FILE.exists():
        return []
    items = []
    for line in REFLEXION_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return items


def extract_commands_from_text(text: str) -> list[str]:
    """Extract shell commands from a text blob (reflection notes)."""
    commands = []
    shell_prefixes = ("docker ", "sudo ", "kopia ", "systemctl ", "git ",
                      "bash ", "curl ", "rm ", "mkdir ", "cp ", "mv ",
                      "rclone ", "pg_dump", "docker-compose ")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(shell_prefixes):
            commands.append(line)
    return commands


def extract():
    """Extract L1 bash skills from recent successful L2 Claude fixes."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    reflexions = load_reflexions()
    extracted = 0

    for r in reflexions:
        if r.get("outcome") != "success":
            continue

        reflection = r.get("reflection", "")
        gene_id = r.get("gene_id", "unknown")
        target = r.get("target", "unknown")

        commands = extract_commands_from_text(reflection)
        if not commands:
            continue

        # Build a searchable skill name
        skill_name = f"{gene_id.replace('gene_', '')}_{target}".replace(":", "_")
        skill_name = re.sub(r'[^a-zA-Z0-9_-]', '_', skill_name)
        skill_file = SKILLS_DIR / f"{skill_name}.sh"

        # Don't overwrite existing
        if skill_file.exists():
            continue

        # Build the script
        script = f"""#!/bin/bash
# Auto-extracted L1 skill from successful L2 Claude fix
# Gene: {gene_id}
# Target: {target}
# Source: reflexion_memory
# Timestamp: {r.get('timestamp', 'unknown')}

set -euo pipefail

"""
        for cmd in commands:
            script += f"{cmd}\n"

        # Add verification
        script += f"""
# Verification
echo "Skill {skill_name} applied. Verify manually or via verify_fix()."
"""

        skill_file.write_text(script)
        os.chmod(skill_file, 0o755)
        extracted += 1
        log(f"Extracted skill: {skill_file.name} ({gene_id} -> {target})")

    log(f"Extraction complete: {extracted} new skill(s)")
    rebuild_index()
    return extracted


def rebuild_index():
    """Rebuild the search index from skill files."""
    index = {}
    if not SKILLS_DIR.exists():
        INDEX_FILE.write_text("{}")
        return

    for skill_file in SKILLS_DIR.glob("*.sh"):
        try:
            content = skill_file.read_text()
            # Extract keywords from filename and content
            keywords = set()
            # From filename
            name_parts = skill_file.stem.replace("_", " ").split()
            keywords.update(name_parts)
            # From content (shell commands)
            for line in content.splitlines():
                if line.startswith("#"):
                    continue
                # Extract command names
                cmd_match = re.match(r'^(\S+)', line)
                if cmd_match:
                    keywords.add(cmd_match.group(1))
                # Extract arguments that look like issue types
                for kw in ["oom", "crash", "restart", "backup", "kopia",
                           "dns", "disk", "memory", "config", "permission"]:
                    if kw in line.lower():
                        keywords.add(kw)

            index[skill_file.stem] = {
                "file": str(skill_file),
                "keywords": sorted(keywords),
                "size": skill_file.stat().st_size,
                "created": datetime.now(timezone.utc).isoformat(),
            }
        except Exception:
            pass

    INDEX_FILE.write_text(json.dumps(index, indent=2))
    log(f"Index rebuilt: {len(index)} skills")


def search(query: str) -> list[dict]:
    """Search skills by keyword."""
    if not INDEX_FILE.exists():
        rebuild_index()

    index = json.loads(INDEX_FILE.read_text())
    query_lower = query.lower()
    results = []

    for name, info in index.items():
        score = 0
        # Check filename
        if query_lower in name.lower():
            score += 3
        # Check keywords
        for kw in info.get("keywords", []):
            if query_lower in kw.lower():
                score += 1
        if score > 0:
            results.append({"name": name, "score": score, **info})

    results.sort(key=lambda x: -x["score"])
    return results


def apply(skill_name: str) -> dict:
    """Execute a skill script."""
    skill_file = SKILLS_DIR / f"{skill_name}.sh"
    if not skill_file.exists():
        # Try without .sh extension
        skill_file = SKILLS_DIR / f"{skill_name}"
    if not skill_file.exists():
        return {"status": "error", "message": f"Skill not found: {skill_name}"}

    try:
        result = subprocess.run(
            ["bash", str(skill_file)],
            capture_output=True, text=True, timeout=300,
        )
        return {
            "status": "success" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "stdout": result.stdout[-500:],
            "stderr": result.stderr[-500:],
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "message": "Skill execution timed out (300s)"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_skills() -> list[str]:
    """List all available skills."""
    if not SKILLS_DIR.exists():
        return []
    return sorted([f.stem for f in SKILLS_DIR.glob("*.sh") if not f.name.startswith(".")])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="L1 skill library")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("extract", help="Extract skills from successful L2 fixes")
    sub.add_parser("index", help="Rebuild search index")
    sub.add_parser("list", help="List all skills")

    search_p = sub.add_parser("search", help="Search skills by keyword")
    search_p.add_argument("query", help="Search term")

    apply_p = sub.add_parser("apply", help="Execute a skill")
    apply_p.add_argument("skill", help="Skill name")

    args = parser.parse_args()

    if args.command == "extract":
        count = extract()
        print(f"Extracted {count} new skill(s)")
    elif args.command == "index":
        rebuild_index()
        print(f"Index rebuilt: {len(list_skills())} skills")
    elif args.command == "list":
        skills = list_skills()
        if skills:
            print(f"\n{len(skills)} skills:\n")
            for s in skills:
                print(f"  {s}")
        else:
            print("No skills found.")
    elif args.command == "search":
        results = search(args.query)
        if results:
            print(f"\nFound {len(results)} skill(s) matching '{args.query}':\n")
            for r in results:
                print(f"  {r['name']} (score: {r['score']})")
                print(f"    Keywords: {', '.join(r.get('keywords', [])[:10])}")
        else:
            print(f"No skills found matching '{args.query}'")
    elif args.command == "apply":
        result = apply(args.skill)
        print(json.dumps(result, indent=2))
