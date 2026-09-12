#!/usr/bin/env python3
"""experience_builds.py — shared backbone for the four "transformative experience"
modules: state_verdict, soul_avatar, human_overrides, life_radiator.

Provides:
  * safe file reads (JSON / plain text) that never crash on missing data
  * page_telegram()     -> best-effort Telegram send w/ graceful degrade
  * is_personal_domain(action_key) -> is this a change to *my* data (needs human)?
  * trial_tag(action_key, approved) -> mark an approved action reversible
  * open_state/commit_state -> tiny JSON state (last-run windows, dedup)
  * recent_failures(gene, target, hours) -> evidence used by several modules

All functions are defensive: on any error they return a safe default and
never raise, so a single flaky subsystem can't break the autonomous stack.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
SCRIPTS = HERMES_HOME / "scripts"
STATE = HERMES_HOME / "state"
DATA = HERMES_HOME / "data"
UM_DB = DATA / "unified_memory.db"

# Touch your data if the action mentions these (personal jurisdiction)
PERSONAL_TOKENS = (
    "journal", "bio", "personal", "profile", "memory", "notes",
    "commitment", "goal", "calendar", "email", "persona", "inbox",
    "messages", "observations", "narrative", "soul", "theta",
)

# Trial-suffix marker appended to infra actions so they run reversibly
TRIAL_MARK = "[trial]"


# ─────────────────────────────────────────────────────────────────────────
# Safe I/O
# ─────────────────────────────────────────────────────────────────────────
def read_json(path: Path, default):
    try:
        if path.exists():
            data = json.loads(path.read_text())
            return data if isinstance(data, type(default)) else default
    except Exception:
        pass
    return default


def write_json(path: Path, data) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))
        return True
    except Exception:
        return False


def read_text(path: Path, default: str = "") -> str:
    try:
        if path.exists():
            return path.read_text(errors="ignore")
    except Exception:
        pass
    return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────────────
def page_telegram(text: str) -> str:
    """Best-effort page. Returns 'sent' | 'skipped-unavailable' | 'error'."""
    try:
        sys.path.insert(0, str(HERMES_HOME / "hermes-agent" / "scripts" / "lib"))
        import telegram_send  # type: ignore
        if telegram_send.send_telegram(text, dedup=True):
            return "sent"
        return "skipped-duplicate"
    except Exception:
        # graceful: never let credential issues crash autonomous work
        return "skipped-unavailable"


# ─────────────────────────────────────────────────────────────────────────
# Jurisdiction: does this action touch *your* data?
# ─────────────────────────────────────────────────────────────────────────
def is_personal_domain(action_key: str) -> bool:
    low = (action_key or "").lower()
    return any(tok in low for tok in PERSONAL_TOKENS)


def trial_tag(action_key: str) -> str:
    """Mark an approved infra action as reversible with a [trial] suffix."""
    if not action_key or action_key.endswith(TRIAL_MARK):
        return action_key
    return f"{action_key} {TRIAL_MARK}"


# ─────────────────────────────────────────────────────────────────────────
# Tiny state window (dedup / last-run)
# ─────────────────────────────────────────────────────────────────────────
_STATE_FILES: dict = {}

def open_state(name: str) -> dict:
    name = name.replace("/", "_")
    if name not in _STATE_FILES:
        _STATE_FILES[name] = read_json(STATE / f"exp_{name}.json", {})
    return _STATE_FILES[name]


def commit_state(name: str, data: dict) -> bool:
    name = name.replace("/", "_")
    _STATE_FILES[name] = data
    return write_json(STATE / f"exp_{name}.json", data)


def within_window(name: str, hours: float) -> bool:
    """True if <last_run> for this window is within hours ago (dedup)."""
    st = open_state(name)
    last = st.get("last_run")
    if not last:
        return False
    try:
        dt = datetime.fromisoformat(last)
        return datetime.now(timezone.utc) - dt < timedelta(hours=hours)
    except Exception:
        return False


def mark_run(name: str, **extra) -> dict:
    st = open_state(name)
    st["last_run"] = _now()
    st.update(extra)
    commit_state(name, st)
    return st


# ─────────────────────────────────────────────────────────────────────────
# Evidence helpers used by several modules
# ─────────────────────────────────────────────────────────────────────────
def recent_failures(gene: str | None = None, target: str | None = None,
                    hours: float = 24) -> int:
    try:
        c = sqlite3.connect(UM_DB)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        q = "SELECT COUNT(*) FROM outcomes WHERE outcome='fail' AND timestamp > ?"
        args: list = [cutoff]
        if gene:
            q += " AND gene_id=?"
            args.append(gene)
        if target:
            q += " AND target=?"
            args.append(target)
        row = c.execute(q, args).fetchone()
        c.close()
        return row[0] if row else 0
    except Exception:
        return 0


def recent_outcomes(hours: float = 24) -> list[dict]:
    try:
        c = sqlite3.connect(UM_DB)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = c.execute(
            "SELECT timestamp, gene_id, target, outcome, notes FROM outcomes "
            "WHERE timestamp > ? ORDER BY timestamp DESC", (cutoff,)
        ).fetchall()
        c.close()
        return [dict(zip(("timestamp", "gene_id", "target", "outcome", "notes"), r)) for r in rows]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────
# DB access helper for decision_register (shared by verdict + overrides)
# ─────────────────────────────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    return sqlite3.connect(UM_DB)


DECISION_COLS = (
    "id, summary, context, owner, stakeholders, impact, domain, status, priority, "
    "due_date, outcome, follow_up, source, created_at, updated_at, completed_at"
)


def insert_decision(conn, summary, context="", owner="hermes_mind/speaker",
                    stakeholders=None, impact="medium", domain="personal",
                    status="pending", priority="medium", source="experience",
                    due_date=None) -> str:
    """Insert a row into decision_register; returns the new id."""
    pid = "E" + _now().replace("-", "").replace(":", "").replace(".", "")[:14] + os.urandom(2).hex()[:4]
    now = _now()
    conn.execute(
        f"INSERT INTO decision_register ({DECISION_COLS}) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, summary, context, owner,
         json.dumps(stakeholders or []), impact, domain, status, priority,
         due_date, None, None, source, now, now, None),
    )
    conn.commit()
    return pid