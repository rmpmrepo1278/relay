#!/usr/bin/env python3
"""skills_reindex.py — reconcile the 3 skill systems into skills/index.json.

The skills/ dir holds:
  1. hash-<uuid>.json  -> legacy global skills (already in index.json "skills")
  2. <name>.skill.md   -> skills_lib runnable skills
  3. <topic>/ dirs     -> capability folders (chief-of-staff/scripts, etc.)

index.json is READ-ONLY metadata for tools that list skills. This reindexer
regenerates it from disk so the catalog always matches reality (fixes the
audit finding "index knows 11 of 34"). It preserves the existing entries for
hash-json skills and adds .skill.md + dir entries via stable ids.

CLI:
  python3 skills_reindex.py          # rebuild skills/index.json from disk
  python3 skills_reindex.py --check  # print what WOULD change vs current
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_kits import HERMES_HOME

SKILLS = HERMES_HOME / "skills"
INDEX = SKILLS / "index.json"


def _md5(s: str) -> str:
    import hashlib
    return hashlib.md5(s.encode()).hexdigest()


def scan() -> dict:
    """Collect every skill-ish entry currently on disk."""
    entries = {}

    # 1) legacy hash-json entries (parse name); skip dotfiles/usage-tracker
    for p in sorted(SKILLS.glob("*.json")):
        if p.name == "index.json" or p.name.startswith("."):
            continue
        try:
            data = json.loads(p.read_text())
            name = data.get("name") or p.stem
            entries[p.stem] = {
                "id": p.stem, "name": name,
                "description": data.get("description", ""),
                "when_to_use": data.get("when_to_use", ""),
                "source": "legacy-json",
                "path": str(p),
            }
        except Exception:
            continue

    # 2) skills_lib .skill.md files
    for p in sorted(SKILLS.glob("*.skill.md")):
        pid = "skill_" + _md5(p.stem)[:10]
        desc = ""
        text = p.read_text(errors="replace")
        for line in text.splitlines():
            if line.strip().startswith("description:"):
                desc = line.split(":", 1)[1].strip()
                break
        entries[pid] = {
            "id": pid, "name": p.name[: -len(".skill.md")],
            "description": desc, "when_to_use": "",
            "source": "skillmd", "path": str(p),
        }

    # 3) capability dirs (exclude scripts/ etc.)
    for d in sorted(SKILLS.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        did = "dir_" + _md5(d.name)[:10]
        entries[did] = {
            "id": did, "name": d.name,
            "description": "capability folder", "when_to_use": "",
            "source": "dir", "path": str(d),
        }

    return entries


def build() -> dict:
    entries = scan()
    ids = sorted(entries)
    return {
        "skills": entries,
        "pinned": [],
        "global_skills": ids,
        "count": len(ids),
        "rebuilt_at": __import__("agent_kits").now_iso(),
    }


def current() -> dict:
    try:
        return json.loads(INDEX.read_text())
    except Exception:
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)

    new = build()
    old = current()
    new_ids = set(new["global_skills"])
    old_ids = set(old.get("global_skills", []))

    if args.check:
        missing = sorted(new_ids - old_ids)
        stale = sorted(old_ids - new_ids)
        print(f"catalog would have {len(new_ids)} entries (currently {len(old_ids)}).")
        if missing:
            print("newly discovered:")
            for i in missing[:20]:
                e = new["skills"][i]
                print(f"  + {e['source']:12} {e['name']}")
        if stale:
            print("stale (removed from index):")
            for i in stale[:20]:
                print(f"  - {i}  (was {old.get('skills', {}).get(i, {}).get('name', '?')})")
        return 0

    INDEX.write_text(json.dumps(new, indent=2))
    print(f"reindexed skills/ -> {len(new_ids)} entries in {INDEX.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())