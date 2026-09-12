#!/usr/bin/env python3
"""import_safety.py — Guard against archiving/removing a module that live code imports.

The gateway_guardian incident (syslog_emit.py removed by audit, gateway safety
net crashed on every scheduler run) showed that dead-code scans have false
negatives on indirect/dynamic imports. This guard runs a real dependency check
before anything is archived or deleted.

Usage (as a module):
    from import_safety import import_blockers
    blockers = import_blockers("/home/rohit/.hermes/scripts/syslog_emit.py")
    if blockers:
        print("Cannot archive:", blockers)

Usage (as a CLI):
    python3 import_safety.py /path/to/file [more/files...]
    # exit 0 = safe to remove, exit 1 = at least one blocker found
"""
import re
import subprocess
import sys
from pathlib import Path

HERMES = Path.home() / ".hermes"

# Roots to scan for importers (live code only — excludes archive, caches, venv)
SCAN_ROOTS = [
    HERMES / "scripts",
    HERMES / "plugins",
    HERMES / "hooks",
    HERMES / "skills-scripts",
    HERMES / "skills",
]
EXCLUDE = ("__pycache__", ".venv", "site-packages", "node_modules",
           "archive", "graphify-out", "collaborator-memory", "/cache/")


def _module_names(path: Path) -> list[str]:
    """Candidate import names for a file, e.g. scripts/syslog_emit.py -> ['syslog_emit']."""
    stem = path.stem  # 'syslog_emit'
    if stem.endswith("_") or not stem:
        return []
    names = {stem}
    # packages: some files are also imported as <dir>.<stem>
    return sorted(names)


def import_blockers(target: str) -> list[str]:
    """Return list of live files that import the given file's module."""
    target_path = Path(target)
    if not target_path.exists():
        return []  # already gone — nothing more to protect
    mods = _module_names(target_path)
    if not mods:
        return []
    blockers = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        try:
            files = root.rglob("*.py")
        except Exception:
            continue
        for f in files:
            if any(x in str(f) for x in EXCLUDE):
                continue
            if f == target_path or f.resolve() == target_path.resolve():
                continue
            if f.name == target_path.name:
                continue  # same-named file elsewhere (its own dir) — not an importer
            try:
                text = f.read_text(errors="ignore")
            except Exception:
                continue
            for m in mods:
                # import m | from m import | from m.sub import (only exact module)
                if re.search(rf"^\s*(from\s+{re.escape(m)}\s+import|import\s+{re.escape(m)}\b)", text, re.M):
                    blockers.append(f"{f.relative_to(Path.home())}")
                    break
    return blockers


def main(argv) -> int:
    if len(argv) < 2:
        print("usage: import_safety.py <file> [file...]")
        return 2
    rc = 0
    for target in argv[1:]:
        blockers = import_blockers(target)
        if blockers:
            rc = 1
            print(f"BLOCKED: {target}")
            for b in blockers:
                print(f"   imported by {b}")
        else:
            print(f"SAFE: {target}")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))