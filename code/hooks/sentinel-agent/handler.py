"""Sentinel Agent Gateway Hook.

Fires on gateway startup to run a full system sweep.
Fires on session:end to auto-extract key facts into claudemem.
Fires on agent:end to check for execution errors.
"""

import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

HERMES_HOME = Path(os.environ.get("HERMES_HOME")) if os.environ.get("HERMES_HOME") else Path.home() / ".hermes"
STATE_DIR = HERMES_HOME / "state"
STATE_DB = HERMES_HOME / "state.db"
CLAUDEMEM_DB = HERMES_HOME / "claudemem.db"


def handle(event_type: str, context: dict) -> None:
    """Gateway hook handler."""
    if event_type == "gateway:startup":
        _on_startup(context)
    elif event_type == "session:end":
        _on_session_end(context)
    elif event_type == "agent:end":
        _on_agent_end(context)
    elif event_type == "command:sentinel":
        _on_command(context)


def _on_startup(context: dict) -> None:
    """Run a full system sweep on gateway startup.

    Gracefully skips when the sentinel module or agent root isn't present
    (e.g. in the hermes Docker container where the agent symlink target
    isn't mounted). This avoids a noisy error at every restart.
    """
    agent_root = HERMES_HOME / "hermes-agent"
    sentinel_pkg = agent_root / "plugins" / "sentinel" / "log_watcher.py"
    if not sentinel_pkg.exists() or not agent_root.is_dir():
        logger.info("sentinel: startup sweep skipped (module not found at %s)", sentinel_pkg)
        return
    try:
        logger.info("sentinel: gateway startup — running system sweep")
        result = subprocess.run(
            [sys.executable, "-m", "plugins.sentinel.log_watcher", "--once"],
            capture_output=True, text=True, timeout=60,
            cwd=str(agent_root),
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                findings = json.loads(result.stdout)
                if findings:
                    logger.info("sentinel: startup sweep found %d issues", len(findings))
                    from plugins.sentinel.correlator import process_findings
                    incidents = process_findings(findings)
                    for inc in incidents:
                        logger.info(
                            "sentinel: startup incident %s (%s): %s",
                            inc.incident_id, inc.severity.value, inc.title,
                        )
            except json.JSONDecodeError:
                pass
        logger.info("sentinel: startup sweep complete")
    except Exception as e:
        logger.error("sentinel: startup sweep error: %s", e)


def _on_session_end(context: dict) -> None:
    """On session end: extract key facts into claudemem + check for errors."""
    try:
        session_id = context.get("session_id", "")
        error = context.get("error")

        # 1. Check for session errors
        if error:
            from plugins.sentinel.correlator import process_findings
            finding = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "gateway",
                "label": "session_error",
                "category": "session_error",
                "severity": "medium",
                "description": f"Session ended with error: {str(error)[:100]}",
                "auto_fix_hint": None,
                "raw_line": str(error)[:500],
                "finding_hash": f"session_error:{str(error)[:80]}",
            }
            process_findings([finding])

        # 2. Auto-extract key facts into claudemem
        if session_id:
            _extract_session_facts(session_id)

    except Exception as e:
        logger.error("sentinel: session end check error: %s", e)


def _extract_session_facts(session_id: str) -> None:
    """Extract key facts from a finished session and write to claudemem.

    Reads the session's messages from state.db, identifies important
    facts/decisions/learnings, and writes them as claudemem observations.
    Uses simple heuristic extraction (no LLM call needed) for reliability.
    """
    try:
        if not STATE_DB.exists() or not CLAUDEMEM_DB.exists():
            return

        # Read session messages from state.db
        conn = sqlite3.connect(str(STATE_DB))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get session info
        cursor.execute(
            "SELECT s.id, s.source, s.message_count, s.title, s.started_at, s.ended_at "
            "FROM sessions s WHERE s.id = ?",
            (session_id,)
        )
        session = cursor.fetchone()
        if not session or session["message_count"] < 2:
            conn.close()
            return

        # Get user messages from this session
        cursor.execute(
            "SELECT m.id, m.role, m.content, m.timestamp "
            "FROM messages m WHERE m.session_id = ? ORDER BY m.id ASC",
            (session_id,)
        )
        messages = cursor.fetchall()
        conn.close()

        if not messages:
            return

        # Extract facts heuristically — no LLM needed
        observations = _heuristic_extract(session, messages)

        if not observations:
            return

        # Write to claudemem
        _write_observations(session_id, observations)

        logger.info(
            "sentinel: extracted %d observations from session %s",
            len(observations), session_id[:16]
        )

    except Exception as e:
        logger.warning("sentinel: fact extraction error for %s: %s", session_id[:16], e)


def _heuristic_extract(session: dict, messages: list) -> list:
    """Extract observations from session messages using heuristics.

    Looks for:
    - User statements with "I decided", "we should", "let's use", etc. (decisions)
    - User statements with error/failure keywords (issues encountered)
    - User statements with "how to", "what is", "why does" (learnings)
    - Tool calls that indicate infrastructure changes (docker, systemctl, git)
    - Repeated patterns (user asking same thing multiple times = confusion)
    """
    observations = []
    user_messages = [m for m in messages if m["role"] == "user"]
    assistant_messages = [m for m in messages if m["role"] == "assistant"]

    # Strip username prefix from content
    import re
    def clean_content(content):
        return re.sub(r"^\[[^\]]+\]\s*", "", content or "").strip()

    for msg in user_messages:
        text = clean_content(msg["content"])
        if not text or len(text) < 10:
            continue

        text_lower = text.lower()

        # Decision patterns
        decision_keywords = [
            "i decided", "we should", "let's use", "i'll use", "switching to",
            "going with", "final choice", "settled on", "i want to", "let's go with",
            "i'm going to", "plan is", "approach will be", "solution is to",
        ]
        for kw in decision_keywords:
            if kw in text_lower:
                observations.append({
                    "content": f"Decision: {text[:300]}",
                    "category": "decision",
                    "importance": 0.85,
                })
                break

        # Learning / discovery patterns
        learning_keywords = [
            "i learned", "turns out", "discovered", "found out", "realized",
            "the issue was", "root cause", "the problem is", "solution was",
            "fixed by", "resolved by", "working now", "it works",
        ]
        for kw in learning_keywords:
            if kw in text_lower:
                observations.append({
                    "content": f"Learning: {text[:300]}",
                    "category": "learning",
                    "importance": 0.9,
                })
                break

        # Error / issue patterns
        error_keywords = [
            "error", "failed", "broken", "not working", "issue", "problem",
            "bug", "crash", "exception", "traceback", "timeout",
        ]
        for kw in error_keywords:
            if kw in text_lower:
                observations.append({
                    "content": f"Issue: {text[:300]}",
                    "category": "issue",
                    "importance": 0.8,
                })
                break

        # Infrastructure change patterns
        infra_keywords = [
            "docker", "systemctl", "git push", "git commit", "deploy",
            "install", "update", "upgrade", "restart", "rebuild",
            "compose", "container", "service", "config",
        ]
        for kw in infra_keywords:
            if kw in text_lower:
                observations.append({
                    "content": f"Infra: {text[:300]}",
                    "category": "infrastructure",
                    "importance": 0.75,
                })
                break

    # Detect repeated questions (confusion signal)
    user_texts = [clean_content(m["content"])[:60].lower() for m in user_messages]
    seen = {}
    for i, t in enumerate(user_texts):
        if t in seen and len(t) > 15:
            observations.append({
                "content": f"Repeated question (asked at turn {seen[i]} and {i}): {t}",
                "category": "confusion",
                "importance": 0.7,
            })
        seen[t] = i

    # Deduplicate observations by content prefix
    unique = []
    seen_content = set()
    for obs in observations:
        key = obs["content"][:60]
        if key not in seen_content:
            seen_content.add(key)
            unique.append(obs)

    # Cap at 5 observations per session to avoid noise
    return unique[:5]


def _write_observations(session_id: str, observations: list) -> None:
    """Write extracted observations to claudemem.db."""
    conn = sqlite3.connect(str(CLAUDEMEM_DB))
    cursor = conn.cursor()

    now = time.time()
    for obs in observations:
        obs_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT OR IGNORE INTO observations (id, session_id, timestamp, source, content, importance, compressed, category) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (obs_id, session_id, now, "sentinel-hook", obs["content"], obs["importance"], obs["category"])
        )

    conn.commit()
    conn.close()


def _on_agent_end(context: dict) -> None:
    """Check agent execution for failures."""
    try:
        result = context.get("result", {})
        if isinstance(result, dict) and result.get("status") == "error":
            from plugins.sentinel.correlator import process_findings
            finding = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "gateway",
                "label": "agent_error",
                "category": "agent_error",
                "severity": "medium",
                "description": f"Agent execution failed: {str(result.get('error', 'unknown'))[:100]}",
                "auto_fix_hint": None,
                "raw_line": str(result)[:500],
                "finding_hash": f"agent_error:{str(result.get('error', 'unknown'))[:80]}",
            }
            process_findings([finding])
    except Exception as e:
        logger.error("sentinel: agent end check error: %s", e)


def _on_command(context: dict) -> None:
    """Handle /sentinel command from Telegram."""
    pass
