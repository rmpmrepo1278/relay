#!/usr/bin/env python3
"""record_workflow.py — "Teach a task": turn a demonstrated workflow into a skill.

The Grok-Bot pattern: you show the agent the steps once, it saves them as a
routine (a skills_lib skill) and runs them on demand / on a schedule.

Modes:
  record        capture a command each line on stdin; placeholders become {args}
  file          capture from a file/list of commands (one per line, # = comment)
  run           replay a recorded skill with inputs

Demo:
  echo 'docker compose ps' | python3 record_workflow.py record my-check --desc "check stack"
  python3 record_workflow.py run my-check
  echo 'python3 {} --debug' | python3 record_workflow.py record gen-report --desc "report"
  python3 record_workflow.py run gen-report arg1=report.py
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import skills_lib
from agent_kits import HERMES_HOME, now_iso


def record(name: str, lines: list[str], description: str = "") -> dict:
    name = re.sub(r"[^A-Za-z0-9_-]", "", name or "")
    if not name or not lines:
        return {"ok": False, "error": "need a name and at least one step"}
    steps = []
    seen_args = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        steps.append(ln)
        for m in re.findall(r"{([A-Za-z0-9_]+)}", ln):
            if m not in seen_args:
                seen_args.append(m)
    if not steps:
        return {"ok": False, "error": "no steps given"}
    md = [
        "---",
        f"name: {name}",
        f"description: {description or 'recorded workflow'}"
        "",
        "## Steps",
    ]
    for i, s in enumerate(steps, 1):
        md.append(f"{i}. {s}")
    md += ["", "## Validation", "- ok", "", "## Failure", "- echo \"step failed\"",
           "", "## Approval", "- auto", "", "## Inputs"]
    for a in seen_args:
        md.append(f"- {a}: (documented placeholder)")
    path = skills_lib.SKILLS_DIR / f"{name}.skill.md"
    skills_lib.SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(md) + "\n")
    return {"ok": True, "name": name, "steps": steps, "path": str(path), "args": seen_args}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_rec = sub.add_parser("record", aliases=["teach"])
    p_rec.add_argument("name")
    p_rec.add_argument("--desc", default="recorded workflow")
    p_rec.add_argument("--file", default="")
    p_rec.add_argument("--lines", nargs="*", default=None)
    p_run = sub.add_parser("run"); p_run.add_argument("name"); p_run.add_argument("kv", nargs="*")
    args = ap.parse_args(argv)

    if args.cmd in ("record", "teach"):
        if args.lines:
            lines = args.lines
        elif args.file:
            lines = Path(args.file).read_text().splitlines()
        else:
            lines = sys.stdin.read().splitlines()
        r = record(args.name, lines, args.desc)
        print(f"recorded {r['name']} ({len(r['steps'])} steps)" if r["ok"] else r["error"])
        if r["ok"]:
            print(f"path: {r['path']}")
    elif args.cmd == "run":
        inputs = {}
        for kv in args.kv:
            if "=" in kv:
                k, _, v = kv.partition("=")
                inputs[k.strip()] = v
        print(skills_lib.run(args.name, inputs))
    return 0


if __name__ == "__main__":
    sys.exit(main())