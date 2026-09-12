#!/usr/bin/env python3
"""
insight_engine.py — Cross-Domain Insight Engine for Hermes.

Reads signals from ALL intelligence modules and finds non-obvious connections
between domains that no single module would catch on its own.

This is the "connective tissue" that turns 30 isolated modules into a mind.

Key insight patterns:
- Health + Career: System instability during interview prep → fix first
- Research + Infra: New paper on virtualization → relevant to current Docker issues
- Email + Calendar: Actionable email + meeting soon → prioritize now
- Goals + Time: Stalled goal + free time window → nudge to work on it
- External + Personal: HN trending topic + your skills → opportunity
- Financial + Calendar: Subscription renewal + low balance → warn
- Wellness + Productivity: Stress pattern + heavy workload → suggest break

Usage:
    python3 insight_engine.py              # Generate insights
    python3 insight_engine.py --json       # Output as JSON
    python3 insight_engine.py --top N      # Return top N insights
"""

from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

HERMES_HOME = Path.home() / ".hermes"
STATE_DIR = HERMES_HOME / "state"
DATA_DIR = HERMES_HOME / "data"
LOG_DIR = HERMES_HOME / "logs"


def _run(cmd: list[str], timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _read_json(path: str) -> dict:
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Signal gatherers — read from each module's output/state
# ---------------------------------------------------------------------------
def get_health_signals() -> dict:
    """Get current health status."""
    return _read_json(f"{STATE_DIR}/health_signals.json")


def get_goal_signals() -> dict:
    """Get active goals and their status."""
    return _read_json(f"{STATE_DIR}/goal_state.json") or _read_json(f"{STATE_DIR}/autonomous_goal_state.json")


def get_task_queue_signals() -> dict:
    """Get pending tasks."""
    return _read_json(f"{STATE_DIR}/task_queue.json")


def get_email_signals() -> dict:
    """Get recent email summary."""
    out = _run(["python3", f"{HERMES_HOME}/scripts/email_intelligence.py", "--digest"], timeout=30)
    return {"raw": out, "has_actionable": "actionable" in out.lower() and "no actionable" not in out.lower()}


def get_calendar_signals() -> dict:
    """Get upcoming calendar events."""
    out = _run(["python3", f"{HERMES_HOME}/scripts/proactive/calendar_manager.py", "--upcoming"], timeout=15)
    return {"raw": out, "has_upcoming": bool(out and len(out) > 50)}


def get_capsule_signals() -> dict:
    """Get recent capsule outcomes (what strategies worked/failed)."""
    jsonl = HERMES_HOME / "capsules" / "outcomes.jsonl"
    capsules = []
    if jsonl.exists():
        lines = jsonl.read_text().strip().split("\n")
        parsed = []
        for l in lines[-20:]:
            if not l.strip():
                continue
            try:
                parsed.append(json.loads(l))
            except json.JSONDecodeError:
                continue
        capsules = parsed
    if not capsules:
        legacy = _read_json(f"{STATE_DIR}/capsule_outcomes.json")
        capsules = legacy if isinstance(legacy, list) else []
    return {"recent": capsules[-5:] if capsules else []}


def get_conversation_signals() -> dict:
    """Get recent conversation context from agent log."""
    log_file = LOG_DIR / "agent.log"
    if not log_file.exists():
        return {}
    try:
        out = _run(["grep", "inbound message", str(log_file)], timeout=5)
        lines = out.split("\n")[-10:] if out else []
        return {"recent_messages": lines}
    except Exception:
        return {}


def get_mind_loop_signals() -> dict:
    """Get the mind loop's own state."""
    return _read_json(f"{STATE_DIR}/mind_loop.json")


def get_external_signals() -> dict:
    """Get external signals (HN, arXiv, GitHub)."""
    signals = {}

    # HN top stories
    try:
        import urllib.request
        req = urllib.request.Request("https://hacker-news.firebaseio.com/v0/topstories.json")
        with urllib.request.urlopen(req, timeout=10) as r:
            ids = json.loads(r.read())[:15]
        stories = []
        for i in ids[:8]:
            req2 = urllib.request.Request(f"https://hacker-news.firebaseio.com/v0/item/{i}.json")
            with urllib.request.urlopen(req2, timeout=10) as r2:
                s = json.loads(r2.read())
                stories.append({"score": s.get("score", 0), "title": s.get("title", "")[:100]})
        signals["hn_top"] = stories
    except Exception:
        pass

    return signals


# ---------------------------------------------------------------------------
# Insight generators — the actual cross-domain reasoning
# ---------------------------------------------------------------------------
def generate_insights(signals: dict) -> list:
    """Generate cross-domain insights from all signals."""
    insights = []

    health = signals.get("health", {})
    goals = signals.get("goals", {})
    tasks = signals.get("tasks", {})
    email = signals.get("email", {})
    calendar = signals.get("calendar", {})
    capsules = signals.get("capsules", {})
    conversations = signals.get("conversations", {})
    mind_loop = signals.get("mind_loop", {})
    external = signals.get("external", {})

    health_checks = health.get("checks", {})
    health_score = health.get("score", 100)

    # ── Pattern 1: Health + Productivity ──
    failed_checks = [n for n, c in health_checks.items() if c.get("status") not in ("ok", "healthy")]
    if failed_checks and health_score < 80:
        # Check if Rohit has been active recently (might be trying to work)
        recent_msgs = conversations.get("recent_messages", [])
        if len(recent_msgs) > 3:
            insights.append({
                "type": "health_productivity",
                "severity": "high",
                "content": f"System health degraded ({health_score}/100, {len(failed_checks)} issues) while you're actively working. Issues: {', '.join(failed_checks[:3])}. This could impact your workflow.",
                "action": "fix_health_first",
                "domains": ["infrastructure", "productivity"],
            })

    # ── Pattern 2: Stalled Goals + Available Time ──
    active_goals = goals.get("goals", []) if isinstance(goals, dict) else []
    stalled = [g for g in active_goals if g.get("status") == "stalled"]
    pending_tasks = tasks.get("tasks", []) if isinstance(tasks, dict) else []
    high_priority = [t for t in pending_tasks if t.get("priority", 0) >= 7 and t.get("status") == "pending"]

    if stalled and not high_priority:
        goal_titles = [g.get("title", "?") for g in stalled[:2]]
        insights.append({
            "type": "goal_opportunity",
            "severity": "medium",
            "content": f"Stalled goals with no high-priority tasks blocking: {', '.join(goal_titles)}. Good time to make progress.",
            "action": "suggest_goal_work",
            "domains": ["career", "goals", "productivity"],
        })

    # ── Pattern 3: Email Urgency + Calendar ──
    if email.get("has_actionable") and calendar.get("has_upcoming"):
        insights.append({
            "type": "time_pressure",
            "severity": "high",
            "content": "Actionable emails waiting + upcoming calendar events. May need to triage before your meeting.",
            "action": "surface_email_summary",
            "domains": ["email", "calendar", "productivity"],
        })

    # ── Pattern 4: External Signal + Personal Relevance ──
    hn_top = external.get("hn_top", [])
    relevance_keywords = {
        "ai_agents": ["ai", "llm", "agent", "gpt", "claude", "copilot", "agentic"],
        "infrastructure": ["docker", "kubernetes", "devops", "homelab", "self-host", "proxmox", "vm"],
        "career": ["hiring", "layoff", "remote", "tpm", "program manager", "director"],
        "programming": ["rust", "python", "typescript", "open source", "github"],
    }

    for story in hn_top:
        title = story.get("title", "").lower()
        score = story.get("score", 0)
        for domain, keywords in relevance_keywords.items():
            if any(kw in title for kw in keywords) and score > 100:
                insights.append({
                    "type": "external_relevance",
                    "severity": "low",
                    "content": f"Trending on HN ({score} pts): {story['title'][:80]} — relevant to your {domain} interests.",
                    "action": "surface_link",
                    "domains": ["external", domain],
                    "score": score,
                })
                break  # one domain match per story

    # ── Pattern 5: Capsule Learning ──
    recent_capsules = capsules.get("recent", [])
    failures = [c for c in recent_capsules if c.get("outcome") == "failure"]
    if len(failures) >= 2:
        failure_types = [c.get("issue_type", "?") for c in failures[:3]]
        insights.append({
            "type": "pattern_learning",
            "severity": "medium",
            "content": f"Repeated failures in: {', '.join(failure_types)}. Pattern detected — may need a different approach.",
            "action": "suggest_alternative_strategy",
            "domains": ["learning", "infrastructure"],
        })

    # ── Pattern 6: Mind Loop Self-Awareness ──
    mind_insights = mind_loop.get("insights", [])
    if len(mind_insights) > 10:
        # Check if we're generating insights but not acting
        recent_actions = mind_loop.get("action_history", [])
        if len(recent_actions) < len(mind_insights) * 0.3:
            insights.append({
                "type": "self_awareness",
                "severity": "low",
                "content": f"Generating many insights ({len(mind_insights)}) but low action rate. Either insights aren't valuable or execution is blocked.",
                "action": "review_insight_quality",
                "domains": ["meta", "self-improvement"],
            })

    # ── Pattern 7: Time-of-day awareness ──
    hour = datetime.now().hour
    if hour < 6:
        insights.append({
            "type": "time_awareness",
            "severity": "low",
            "content": "Late night/early morning. Good time for autonomous maintenance tasks (backups, updates, cleanup).",
            "action": "run_maintenance",
            "domains": ["infrastructure", "time"],
        })
    elif 9 <= hour <= 11:
        # Check if there's a pattern of morning productivity
        morning_actions = [
            a for a in mind_loop.get("action_history", [])
            if a.get("timestamp") and 9 <= datetime.fromisoformat(a["timestamp"]).hour <= 11
        ]
        if len(morning_actions) > 5:
            insights.append({
                "type": "productivity_pattern",
                "severity": "low",
                "content": "You tend to be productive in the morning. Scheduling important tasks before noon.",
                "action": "optimize_schedule",
                "domains": ["productivity", "time"],
            })

    # ── Pattern 8: Cross-domain opportunity detection ──
    # If infra is healthy + no urgent tasks + career goals exist → suggest career work
    if health_score >= 95 and not high_priority and not email.get("has_actionable"):
        career_goals = [g for g in active_goals if g.get("domain") in ("career", "career-ops")]
        if career_goals:
            insights.append({
                "type": "opportunity_window",
                "severity": "low",
                "content": f"Clear window: all systems healthy, no urgent tasks. Good time to work on: {career_goals[0].get('title', 'career goals')}",
                "action": "suggest_focus_time",
                "domains": ["career", "productivity", "infrastructure"],
            })

    # Deduplicate by type+content similarity
    seen = set()
    unique = []
    for ins in insights:
        key = f"{ins['type']}:{ins['content'][:60]}"
        if key not in seen:
            seen.add(key)
            unique.append(ins)

    return unique


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_insight_engine(top_n: int = 5) -> list:
    """Run the full insight engine pipeline."""
    signals = {
        "health": get_health_signals(),
        "goals": get_goal_signals(),
        "tasks": get_task_queue_signals(),
        "email": get_email_signals(),
        "calendar": get_calendar_signals(),
        "capsules": get_capsule_signals(),
        "conversations": get_conversation_signals(),
        "mind_loop": get_mind_loop_signals(),
        "external": get_external_signals(),
    }

    insights = generate_insights(signals)

    # Sort by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    insights.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 3))

    return insights[:top_n]


if __name__ == "__main__":
    # ── Agent Parliament: council vote (pre-main dispatch) ──────────
    if '--vote-council' in __import__('sys').argv or '--vote' in __import__('sys').argv:
        _os = __import__('os')
        _sys = __import__('sys')
        _dir = _os.path.dirname(_os.path.abspath(__file__))
        _sys.path.insert(0, _os.path.join(_dir, 'lib'))
        try:
            from council_vote import cast_vote as _council_cast
        except Exception:
            _sys.path.insert(0, '/home/rohit/.hermes/hermes-agent/scripts/lib')
            from council_vote import cast_vote as _council_cast
        _dry = '--dry-run' in _sys.argv
        _res = _council_cast('insight_engine', dry=_dry)
        if _dry:
            print('[insight_engine would-cast: ' + '; '.join(f"{_p}={_v}" for _p, _v in _res) or f'[insight_engine] no open proposals')
        else:
            print(f'[insight_engine] cast ' + '; '.join(f"{_p}={_v}" for _p, _v in _res) or f'[insight_engine] no votes needed')
        _sys.exit(0)

    top = 5
    if "--top" in sys.argv:
        idx = sys.argv.index("--top")
        if idx + 1 < len(sys.argv):
            top = int(sys.argv[idx + 1])

    insights = run_insight_engine(top_n=top)

    # Save results for orchestrator
    results_file = DATA_DIR / "insights.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)
    results_file.write_text(json.dumps(insights, indent=2))

    if "--json" in sys.argv:
        print(json.dumps(insights, indent=2))
    else:
        if not insights:
            print("No cross-domain insights this cycle.")
        else:
            print(f"🔍 {len(insights)} cross-domain insight(s):\n")
            for i, ins in enumerate(insights, 1):
                sev = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(ins.get("severity", "low"), "⚪")
                print(f"  {sev} [{ins.get('type', '?')}] {ins.get('content', '')}")
                if ins.get("action"):
                    print(f"     → Suggested action: {ins['action']}")
                print()
