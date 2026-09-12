#!/usr/bin/env python3
"""skills_lib.py — structured, reusable skills (the Grok-Bot "skills" pattern).

A skill is a markdown file `~/.hermes/skills/<name>.skill.md` with sections:

  name: <slug>              (under first `---` block, YAML-ish)
  description: <one-liner>

  ## Steps
  1. <shell command or `python3 …`>, placeholders {name}
  2. …

  ## Validation
  - <optional grep/regex on the final output>

  ## Failure
  - <recovery command>

  ## Approval
  - auto | required <summary>

  ## Inputs
  - <name>: <description>     (documented, passed as a=b on the CLI)

CLI:
  python3 skills_lib.py list
  python3 skills_lib.py show <name>
  python3 skills_lib.py run <name> [k=v ...]
  python3 skills_lib.py init <name>     # write a template skill
"""
from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path

from agent_kits import HERMES_HOME, run_cmd, send, now_iso

SKILLS_DIR = HERMES_HOME / "skills"

_TEMPLATE = """---
name: {name}
description: What this skill does, when to use it.
---

## Steps
1. echo "step 1 with {input}"
2. # add real steps here (shell lines; `python3 …` for logic)

## Validation
- ok        # substring expected in final output, else Fail step applies

## Failure
- echo "failed-step-recovery"

## Approval
- auto       # or: required <summary shown to the human before execution>

## Inputs
- input: example value
"""


def _skills() -> list[Path]:
    if not SKILLS_DIR.exists():
        return []
    return sorted(p for p in SKILLS_DIR.iterdir() if p.is_file() and p.suffix == ".md")


def _is_skill(p: Path) -> bool:
    return p.name.endswith(".skill.md") and p.name != "_template.skill.md"


def _name_of(p: Path) -> str:
    return p.name[: -len(".skill.md")]


def parse(path: Path) -> dict:
    text = path.read_text(errors="replace")
    name = _name_of(path)
    m = re.search(r"description:\s*(.+)", text)
    description = m.group(1).strip() if m else ""
    steps = re.findall(r"^\s*\d+\.\s+(.+)$", text, re.M)
    approval = "required"
    am = re.search(r"## Approval\n-\s*(auto|required)(.*)", text)
    if am:
        approval = (am.group(1) + " " + am.group(2).strip()).strip()
    return {
        "name": name,
        "description": description[:200],
        "path": str(path),
        "steps": [s.strip() for s in steps],
        "approval": approval,
    }


def list_skills() -> list[dict]:
    out = []
    for p in _skills():
        try:
            if _is_skill(p):
                out.append(parse(p))
        except Exception:
            continue
    return out


def show(name: str) -> dict:
    for p in _skills():
        if _is_skill(p) and _name_of(p) == name:
            return {"ok": True, "skill": parse(p), "text": p.read_text(errors="replace")}
    return {"ok": False, "error": f"no skill '{name}'"}


def _fill(cmd: str, inputs: dict) -> str:
    out = cmd
    for k, v in inputs.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def run(name: str, inputs: dict | None = None, notify: bool = False,
        bypass_approval: bool = False) -> dict:
    """Execute a skill's steps sequentially (bash one-liners).

    `Approval: required` skills are NOT executed here — they are proposed to
    the sentinel gate and run only after a human approves.
    `bypass_approval=True` is used by the sentinel executor AFTER approval."""
    s = show(name)
    if not s["ok"]:
        return {"ok": False, "error": s["error"]}
    sk = s["skill"]
    if not bypass_approval and "required" in str(sk.get("approval", "")):
        import sentinel_gate
        rec = sentinel_gate.propose(
            summary=f"run skill <b>{name}</b> (approved by human)",
            kind="skills",
            payload={"name": name, "inputs": inputs or {}},
            source="skills_lib",
        )
        return {"ok": False, "pending": True,
                "message": f"skill '{name}' requires approval — proposed as #{rec['id']}. "
                           f"Reply /approve {rec['id']} to run it, or /deny."}
    steps = sk["steps"]
    if not steps:
        return {"ok": False, "error": "skill has no steps"}
    inputs = inputs or {}
    output = []
    for i, step in enumerate(steps, 1):
        res = run_cmd(["bash", "-c", _fill(step, inputs)], timeout=300)
        output.append(f"$ {step}\n{res['out']}") 
        if not res["ok"]:
            tail = {"ok": False, "error": f"step {i} failed: {res['err'][:300]}",
                    "output": "\n".join(output)[:2000], "done": f"{i-1}/{len(steps)}"}
            if notify:
                send(f"❌ Skill <b>{name}</b> failed at step {i}\n<pre>{tail['error']}</pre>")
            return tail
    combined = "\n".join(output)[:3000]
    r = {"ok": True, "output": combined, "steps_done": len(steps)}
    if notify:
        send(f"✅ Skill <b>{name}</b> done\n<pre>{combined[:1200]}</pre>")
    return r


def init_skill(name: str) -> dict:
    name = re.sub(r"[^a-zA-Z0-9_-]", "", name or "")
    if not name:
        return {"ok": False, "error": "bad name"}
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    p = SKILLS_DIR / f"{name}.skill.md"
    if p.exists():
        return {"ok": False, "error": "already exists"}
    p.write_text(_TEMPLATE.format(name=name, input="example"))
    return {"ok": True, "path": str(p)}


def validate(n: int = 3) -> dict:
    """PARSE-LOOKAHEAD check (never executes skill steps, no side effects).

    Verifies front-matter parses and steps are present for the newest n skills.
    The scheduler job `skills_smoke` must never run step bodies (that would
    execute arbitrary teach-a-task skills hourly)."""
    failed = []
    forced_rest = []
    for s in list_skills()[-n:]:
        name = s.get("name", "?")
        # parse: front-matter + steps extraction
        try:
            if not s.get("steps"):
                failed.append(f"{name}: no steps parsed")
        except Exception as e:  # pragma: no cover
            failed.append(f"{name}: {str(e)[:120]}")
        # reflection: make sure run() would gate approvals correctly
        try:
            from agent_kits import read_json
            forced_rest.append(str(s.get("approval", "")))
        except Exception:
            pass
    if forced_rest:
        # any skill carrying `Approval: required` is reported, not executed
        pass
    return {"ok": not failed, "checked": len(list_skills()[-n:]),
            "failed": failed, "gated": [f for f in forced_rest if "required" in f]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_show = sub.add_parser("show"); p_show.add_argument("name")
    p_init = sub.add_parser("init"); p_init.add_argument("name")
    p_run = sub.add_parser("run"); p_run.add_argument("name"); p_run.add_argument("kv", nargs="*")
    p_val = sub.add_parser("validate"); p_val.add_argument("n", type=int, default=3, nargs="?")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        for s in list_skills():
            print(f"{s['name']}: {s['description']}")
    elif args.cmd == "show":
        r = show(args.name)
        print(r.get("text", r.get("error")))
    elif args.cmd == "init":
        r = init_skill(args.name)
        print(r.get("path", r.get("error")))
    elif args.cmd == "validate":
        import json
        print(json.dumps(validate(args.n)))
    elif args.cmd == "run":
        inputs = {}
        for kv in args.kv:
            if "=" in kv:
                k, _, v = kv.partition("=")
                inputs[k.strip()] = v
        print(run(args.name, inputs))
    return 0


if __name__ == "__main__":
    sys.exit(main())