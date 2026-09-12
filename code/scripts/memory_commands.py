#!/usr/bin/env python3
"""memory_commands.py — editable "topics" memory over the collaborator-memory repo.

Mirrors the Claude-memory "topics file" pattern: short markdown files, one per
topic, you can list / show / append / search / forget. Every change lands in the
shared memory repo (the same files memory/rohit.md etc. that Relay and the
agents read), so correcting memory in Telegram corrects it for everyone.

Topics live in:
  ~/.hermes/collaborator-memory/memory/        (canonical topics, git-tracked)
  ~/.hermes/memory_topics/                     (scratch topics, non-git)

CLI:
  python3 memory_commands.py list
  python3 memory_commands.py show <topic>
  python3 memory_commands.py append <topic> "<text>"
  python3 memory_commands.py forget <topic> "<line-match>"
  python3 memory_commands.py search "<query>"
  python3 memory_commands.py topic-list
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent_kits import HERMES_HOME, sanitize_name, now_iso

MEMORY_DIR = HERMES_HOME / "collaborator-memory" / "memory"
TOPICS_DIR = HERMES_HOME / "memory_topics"

_BACKUP = HERMES_HOME / "data" / "memory_backups"


def _git_if_repo(path: Path) -> str | None:
    """Return the git repo root if path lives in a git-tracked directory, else None."""
    try:
        import subprocess
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           cwd=str(path.parent), capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _best_effort_commit(msg: str) -> bool:
    """Commit every pending change in the memory repo with a descriptive message. No-op if empty."""
    repo = MEMORY_DIR.parent  # ~/.hermes/collaborator-memory
    if not (repo / ".git").exists():
        return False
    try:
        import subprocess
        subprocess.run(["git", "-C", str(repo), "add", "-A"],
                       capture_output=True, timeout=15)
        r = subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", msg, "--no-verify", "--quiet"],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def _topic_path(topic: str, allow_scratch: bool = True) -> Path | None:
    name = sanitize_name(topic)
    if not name:
        return None
    for base in (MEMORY_DIR, TOPICS_DIR):
        p = base / f"{name}.md"
        if p.exists():
            return p
    return None


def _ensure_scratch(name: str) -> Path:
    TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    return TOPICS_DIR / f"{name}.md"


def topic_list() -> list[str]:
    names = []
    for base in (MEMORY_DIR, TOPICS_DIR):
        if base.exists():
            names += sorted(p.stem for p in base.glob("*.md") if p.stem != "MEMORY")
    return sorted(set(names))


def show(name: str, limit: int = 120) -> dict:
    p = _topic_path(name)
    if not p:
        return {"ok": False, "error": f"no topic '{name}'. Try: /memory list"}
    text = p.read_text(errors="replace")
    lines = text.splitlines()
    return {"ok": True, "name": p.stem, "path": str(p),
            "lines": len(lines), "content": "\n".join(lines[:limit]),
            "truncated": len(lines) > limit}


def append(name: str, text: str) -> dict:
    p = _topic_path(name) or _ensure_scratch(name)
    line = f"- {now_iso().replace('T', ' ')[:16]}Z: {text.strip()}"
    try:
        with p.open("a") as f:
            f.write("\n" + line if p.stat().st_size else line)
        # commit to the shared memory repo if this is a tracked file (not scratch)
        if MEMORY_DIR in p.resolve().parents:
            _best_effort_commit(f"memory: append to {p.stem} via Telegram /remember")
        return {"ok": True, "name": p.stem, "path": str(p), "line": line}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def forget(name: str, needle: str, all_matches: bool = True) -> dict:
    p = _topic_path(name)
    if not p:
        return {"ok": False, "error": f"no topic '{name}'"}
    text = p.read_text(errors="replace")
    pat = re.compile(re.escape(needle), re.I)
    kept = [ln for ln in text.splitlines() if not pat.search(ln)]
    removed = sum(1 for ln in text.splitlines() if pat.search(ln))
    if removed == 0:
        return {"ok": False, "error": f"nothing matching '{needle}' in {p.stem}"}
    # Backup before destructive edit
    _BACKUP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, _BACKUP / f"{p.stem}.{now_iso().replace(':', '-')}.backup.md")
    p.write_text("\n".join(kept) + ("\n" if kept and kept[-1] else ""))
    if MEMORY_DIR in p.resolve().parents:
        _best_effort_commit(f"memory: forget {removed} line(s) from {p.stem} via Telegram")
    return {"ok": True, "name": p.stem, "removed": removed, "path": str(p),
            "backup": str(_BACKUP / (p.stem + ".*.backup.md"))}


def search(query: str) -> dict:
    hits = []
    for base in (MEMORY_DIR, TOPICS_DIR):
        if not base.exists():
            continue
        for p in base.glob("*.md"):
            if p.stem == "MEMORY":
                continue
            for i, ln in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if query.lower() in ln.lower():
                    hits.append({"topic": p.stem, "line": i,
                                 "text": ln.strip()[:160]})
    return {"ok": True, "count": len(hits), "hits": hits[:40],
            "total": len(hits)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Topical memory CRUD")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("topic-list")
    p_show = sub.add_parser("show"); p_show.add_argument("topic")
    p_append = sub.add_parser("append"); p_append.add_argument("topic"); p_append.add_argument("text")
    p_forget = sub.add_parser("forget"); p_forget.add_argument("topic"); p_forget.add_argument("needle")
    p_search = sub.add_parser("search"); p_search.add_argument("query")
    args = ap.parse_args(argv)

    if args.cmd in ("list", "topic-list"):
        for t in topic_list():
            print(t)
    elif args.cmd == "show":
        r = show(args.topic)
        print(r.get("content") if r.get("ok") else r.get("error"))
    elif args.cmd == "append":
        print(append(args.topic, args.text).get("line") or "error")
    elif args.cmd == "forget":
        r = forget(args.topic, args.needle)
        print(f"removed {r.get('removed')} matching lines from {r.get('name')}"
              if r.get("ok") else r.get("error"))
    elif args.cmd == "search":
        r = search(args.query)
        for h in r.get("hits", []):
            print(f"{h['topic']}:{h['line']} — {h['text']}")
        print(f"({r.get('count')} matches)")
    return 0


if __name__ == "__main__":
    sys.exit(main())