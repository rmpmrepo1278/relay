#!/usr/bin/env python3
"""
changelog_gen.py — regenerate CHANGELOG.md from git + capsules.

Philosophy: CHANGELOG.md should be a living document generated from reality.
Hand-written narrative entries are preserved; routine commits/capsules auto-appear.

Run:
    python3 changelog_gen.py              # regenerate
    python3 changelog_gen.py --dry-run    # preview
    python3 changelog_gen.py --since 30d  # limit history

Schedule: daily 3am via hermes_scheduler (after nightly backups)
"""
from __future__ import annotations
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

H = Path.home() / ".hermes"
CHANGELOG = H / "CHANGELOG.md"
CAPSULES = H / "capsules" / "outcomes.jsonl"

# Sections: narrative entries (hand-written) are preserved between markers
NARRATIVE_START = "<!-- CHANGELOG-NARRATIVE START -->"
NARRATIVE_END = "<!-- CHANGELOG-NARRATIVE END -->"


def run(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"(error: {e})"


def git_log(since_days: int = 30) -> str:
    since = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%d")
    # Format: hash | date | subject | author
    cmd = (
        f"git -C {H} log --since='{since}' "
        "--pretty=format:'%h | %ad | %s | %an' --date=short "
        "--grep='fix\\|feat\\|refactor\\|add\\|remove\\|update' -i"
    )
    return run(cmd)


def parse_capsules(limit: int = 20) -> list[dict]:
    if not CAPSULES.exists():
        return []
    entries = []
    for line in CAPSULES.read_text().splitlines()[-limit:]:
        try:
            entries.append(eval(line))  # jsonl, safe enough for own data
        except Exception:
            pass
    return entries


def format_capsules(capsules: list[dict]) -> str:
    if not capsules:
        return "_no recent capsules_"
    out = []
    for c in reversed(capsules):  # newest first
        ts = c.get("timestamp", "")[:19].replace("T", " ")
        action = c.get("action", "unknown")
        result = c.get("result", "?")
        target = c.get("target", "")
        out.append(f"- **{ts}** — {action} on `{target}` → **{result}**")
    return "\n".join(out)


def extract_narrative(text: str) -> str:
    """Extract hand-written narrative section between markers."""
    m = re.search(
        rf"{re.escape(NARRATIVE_START)}(.*?){re.escape(NARRATIVE_END)}",
        text, re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def build_changelog(since_days: int = 30) -> str:
    narrative = ""
    if CHANGELOG.exists():
        narrative = extract_narrative(CHANGELOG.read_text())

    git = git_log(since_days)
    capsules = format_capsules(parse_capsules())

    now = datetime.now().strftime("%Y-%m-%d")
    header = f"# CHANGELOG\n\n*Auto-generated {now} — git (last {since_days}d) + capsules. Narrative section is hand-written.*\n"

    sections = []

    if narrative:
        sections.append(f"{NARRATIVE_START}\n{narrative}\n{NARRATIVE_END}")

    sections.append(f"## 🔧 Git Commits (last {since_days}d)\n```\n{git if git else 'none'}\n```")
    sections.append(f"## 📦 Capsule Outcomes (last 20)\n{capsules}")

    return header + "\n\n".join(sections) + "\n"


def main() -> int:
    dry = "--dry-run" in sys.argv
    since = 30
    for arg in sys.argv:
        if arg.startswith("--since="):
            since = int(arg.split("=")[1].rstrip("d"))

    content = build_changelog(since)

    if dry:
        print("=== DRY RUN ===")
        print(content[:2000])
        print("... (truncated)")
        return 0

    CHANGELOG.write_text(content)
    print(f"CHANGELOG.md regenerated ({len(content)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())