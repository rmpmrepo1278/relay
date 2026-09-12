#!/usr/bin/env python3
"""agent_kits.py — shared backbone for the Hermes agent-kit modules.

Provides safe JSON file IO, Telegram send, subprocess, and lock helpers used by
sentinel_gate, voice_ingest, memory_commands, meeting_prep, routine_watcher,
skills_lib, quiet_threads, browser_agent, brief_feed, vault and commands.

All functions are defensive: they return safe defaults and never raise, so a
single flaky subsystem cannot break the autonomous stack (mirrors
lib/experience_builds.py conventions).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import fcntl
    HAVE_FCNTL = True
except ImportError:  # non-POSIX fallback
    HAVE_FCNTL = False

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
SCRIPTS = HERMES_HOME / "scripts"
DATA = HERMES_HOME / "data"
STATE = HERMES_HOME / "state"

for _p in (SCRIPTS, SCRIPTS / "lib"):
    if str(_p) not in (__import__("sys").path):
        __import__("sys").path.insert(0, str(_p))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default):
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, TypeError):
        return default


def write_json(path: Path, data) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _file_lock(path):
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str))
            tmp.replace(path)
        return True
    except OSError:
        return False


def append_jsonl(path: Path, record: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _file_lock(path):
            with path.open("a") as f:
                f.write(json.dumps(record, default=str) + "\n")
        return True
    except OSError:
        return False


def trim_jsonl(path: Path, max_lines: int = 2000) -> bool:
    """Keep only the last max_lines lines of a jsonl file (rotation helper)."""
    try:
        if not path.exists():
            return True
        with _file_lock(path):
            lines = path.read_text().splitlines()
            if len(lines) <= max_lines:
                return True
            path.write_text("\n".join(lines[-max_lines:]) + "\n")
        return True
    except OSError:
        return False


import contextlib
from contextlib import contextmanager


@contextmanager
def _file_lock(path: Path):
    """Context manager: fcntl.flock on a sidecar <path>.lock (best effort)."""
    if not HAVE_FCNTL:
        yield
        return
    lock_path = path.with_name(path.name + ".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    except OSError:
        yield
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def lock(path: Path, stale_seconds: int = 300) -> bool:
    try:
        if path.exists():
            age = time.time() - path.stat().st_mtime
            if age < stale_seconds:
                return False
            path.unlink(missing_ok=True)
        path.touch()
        return True
    except OSError:
        return False


def unlock(path: Path) -> None:
    path.unlink(missing_ok=True)


def send(text: str, chat_id: str | None = None, parse_mode: str = "HTML") -> bool:
    """Send a Telegram message via the bridge. Never raises."""
    text = (text or "")[:4000]
    try:
        from telegram_bridge import send_telegram
        kwargs = {"parse_mode": parse_mode}
        if chat_id:
            kwargs["chat_id"] = chat_id
        return send_telegram(text[:4000], **kwargs).get("status") == "ok"
    except Exception:
        try:
            from experience_builds import page_telegram
            page_telegram(text[:2000])
            return True
        except Exception:
            return False


def run_cmd(argv: list[str], timeout: int = 60) -> dict:
    """Run a command; returns {ok, code, out, err} truncated. Never raises."""
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "out": (proc.stdout or "").strip()[-3000:],
            "err": (proc.stderr or "").strip()[-2000:],
        }
    except FileNotFoundError as e:
        return {"ok": False, "code": 127, "out": "", "err": f"not found: {e.filename}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -1, "out": "", "err": "timeout"}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "code": -2, "out": "", "err": str(e)}


def mask_value(v: str, visible: int = 4) -> str:
    return (v[:visible] + "…" + "*" * 4) if len(v) > visible else "***"


def sanitize_name(name: str) -> str:
    """Topic/file/skill names: alphanumeric + dash/underscore only (no traversal)."""
    return re.sub(r"[^A-Za-z0-9_-]", "", name or "")


def clean_text(html: str) -> str:
    tag = re.compile(r"<[^>]+>")
    return tag.sub("", html or "")


def load_commitments() -> list[dict]:
    """Flatten data/commitments.json into normalized records.
    Returns [{id, text, due, status: open|done, created, updated}] — never raises."""
    try:
        from commitment_tracker import load_commitments as _raw
        raw = _raw()
    except Exception:
        raw = read_json(DATA / "commitments.json", {})
    if isinstance(raw, list):
        raw = {"active": raw, "history": []}
    if not isinstance(raw, dict):
        return []
    out = []
    for rec in list(raw.get("active", [])) + list(raw.get("history", [])):
        if not isinstance(rec, dict):
            continue
        status = str(rec.get("status") or "active").lower()
        norm = "done" if status in ("fulfilled", "done", "completed", "closed",
                                    "resolved", "cancelled", "failed") else "open"
        created = rec.get("created") or rec.get("created_at") or rec.get("added_at") or ""
        out.append({
            "id": str(rec.get("id") or rec.get("cid") or len(out)),
            "text": rec.get("text") or rec.get("commitment") or rec.get("title") or "",
            "due": rec.get("deadline") or rec.get("due") or rec.get("when") or "",
            "status": norm,
            "created": created,
            "updated": rec.get("updated_at") or rec.get("updated") or created,
        })
    return out