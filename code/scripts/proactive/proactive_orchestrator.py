#!/usr/bin/env python3
"""proactive_orchestrator.py — Coordinates proactive intelligence for Hermes.

Runs every 4-6 hours. Pipeline:
  1. Run interest_model to build current profile
  2. Check curious_explorer for serendipitous discoveries
  3. Check insight_engine for cross-domain patterns
  4. Compose unified proactive briefing
  5. Push to alerts_inbox for Telegram delivery (only if new content)

Output:
  - data/proactive_briefing.json — full results
  - alerts_inbox.jsonl — Telegram-ready message
"""

import json
import subprocess
import sys
import os
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
SCRIPTS_DIR = HERMES_HOME / "scripts"
PROACTIVE_DIR = SCRIPTS_DIR / "proactive"
ALERTS_INBOX = Path.home() / ".hermes" / "data" / "alerts_inbox.jsonl"
DATA_DIR = HERMES_HOME / "data"
BRIEFING_FILE = DATA_DIR / "proactive_briefing.json"
STATE_FILE = DATA_DIR / "proactive_orchestrator_state.json"


def _load_json(path, default=None):
    """Load a JSON file, returning default on any error."""
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _load_alerts_inbox():
    """Parse alerts_inbox.jsonl (supports both JSON array and JSONL formats)."""
    if not ALERTS_INBOX.exists():
        return []
    try:
        content = ALERTS_INBOX.read_text().strip()
        if not content:
            return []
        return json.loads(content) if content.startswith("[") else []
    except (json.JSONDecodeError, OSError):
        return []


def run_script(script_path, args=None, timeout=120):
    """Run a Python script and return (success, output)."""
    if not script_path.exists():
        return False, f"Script not found: {script_path}"
    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()[:500]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def read_interest_profile():
    return _load_json(DATA_DIR / "interest_profile.json")


def read_curious_explorer_results():
    p = HERMES_HOME / "research" / "curious_explorer_results.json"
    return _load_json(p) or _load_json(DATA_DIR / "curious_explorer_results.json")


def read_insight_engine_results():
    return _load_json(HERMES_HOME / "data" / "insights.json")


def format_briefing(profile, curious, insights):
    lines = ["🧠 Proactive Briefing", ""]
    now = datetime.now(timezone.utc).strftime("%a %b %d %H:%M UTC")
    lines.append(f"Generated: {now}")

    if profile:
        topics = profile.get("topics", {})
        dominant = profile.get("dominant", "unknown")
        lines.append(f"\n🎯 Current focus: {dominant}")
        lines.append("Interest weights:")
        for topic, weight in list(topics.items())[:3]:
            bar = "█" * max(1, int(weight / 10))
            lines.append(f"  {topic:20s} {bar} {weight:.1f}%")

    if curious:
        findings = curious if isinstance(curious, list) else curious.get("findings", curious.get("discoveries", []))
        if findings:
            lines.append(f"\n🔍 Top finds ({min(len(findings),3)}):")
            for f in findings[:3]:
                if isinstance(f, dict):
                    title = f.get("title", f.get("name", "unknown"))[:60]
                    lines.append(f"  • {title}")

    if insights:
        items = insights if isinstance(insights, list) else insights.get("insights", [])
        if items:
            lines.append(f"\n💡 Insights ({min(len(items),2)}):")
            for ins in items[:2]:
                if isinstance(ins, dict):
                    lines.append(f"  • {ins.get('insight', ins.get('title', 'unknown'))[:60]}")

    return "\n".join(lines)


def _hash_message(msg):
    return hashlib.md5(msg.encode()).hexdigest()[:8]


def was_recently_delivered(_message_hash=None):
    """Check if a similar message was delivered in the last 12 hours."""
    alerts = _load_alerts_inbox()
    cutoff = datetime.now(timezone.utc).timestamp() - 12 * 3600
    for a in alerts:
        if a.get("source") == "proactive_orchestrator":
            ts = a.get("timestamp", "")
            if ts:
                try:
                    msg_ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                    if msg_ts > cutoff:
                        return True
                except (ValueError, TypeError):
                    pass
    return False


def push_to_alerts_inbox(message, severity="info"):
    """Push a message to the alerts inbox for Telegram delivery."""
    msg_hash = _hash_message(message)
    if was_recently_delivered(msg_hash):
        print("Duplicate briefing, skipping delivery")
        return False
    entry = {
        "severity": severity,
        "message": message,
        "source": "proactive_orchestrator",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "delivered": False,
        "requires_approval": False,
        "actions": [],
    }
    try:
        ALERTS_INBOX.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if ALERTS_INBOX.exists():
            try:
                content = ALERTS_INBOX.read_text().strip()
                if content:
                    existing = json.loads(content) if content.startswith("[") else []
            except (json.JSONDecodeError, OSError):
                existing = []
        existing.append(entry)
        ALERTS_INBOX.write_text(json.dumps(existing, indent=2))
        return True
    except OSError as e:
        print(f"Failed to push to alerts_inbox: {e}")
        return False


def orchestrate():
    state = {"last_run": None, "consecutive_failures": 0}
    if STATE_FILE.exists():
        try:
            state.update(json.loads(STATE_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            pass

    results = {}

    profile = read_interest_profile()
    if profile is None:
        ok, out = run_script(PROACTIVE_DIR / "interest_model.py")
        results["interest_model"] = {"success": ok, "output": out[:200] if out else ""}
        profile = read_interest_profile()
    else:
        results["interest_model"] = {"success": True, "cached": True}

    ok, out = run_script(SCRIPTS_DIR / "curious_explorer.py", timeout=180)
    results["curious_explorer"] = {"success": ok, "output": out[:200] if out else ""}
    curious = read_curious_explorer_results()

    ok, out = run_script(SCRIPTS_DIR / "insight_engine.py", timeout=120)
    results["insight_engine"] = {"success": ok, "output": out[:200] if out else ""}
    insights = read_insight_engine_results()

    briefing = format_briefing(profile, curious, insights)
    if os.getenv("PROACTIVE_BRIEFING", "1") == "1":
        pushed = push_to_alerts_inbox(briefing)
    else:
        print("Proactive briefings muted (PROACTIVE_BRIEFING=0)"); pushed = False

    results["briefing"] = {"length": len(briefing), "pushed": pushed}
    results["timestamp"] = datetime.now(timezone.utc).isoformat()

    BRIEFING_FILE.parent.mkdir(parents=True, exist_ok=True)
    BRIEFING_FILE.write_text(json.dumps(results, indent=2))

    state["last_run"] = results["timestamp"]
    if not all(r.get("success", True) for r in results.values() if isinstance(r, dict)):
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
    else:
        state["consecutive_failures"] = 0
    STATE_FILE.write_text(json.dumps(state, indent=2))

    print(f"Briefing generated (pushed: {pushed})")
    return all(r.get("success", True) for r in results.values() if isinstance(r, dict))


if __name__ == "__main__":
    success = orchestrate()
    sys.exit(0 if success else 1)