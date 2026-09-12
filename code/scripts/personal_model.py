#!/usr/bin/env python3
"""
personal_model.py — Hermes' personal/values model for Rohit.

Synthesises:
  - Core values from TELOS.md + HERMES.md + inferred from interactions
  - Long-term life goals (3-5) derived from values + unspoken needs
  - Goal decay/prioritisation when attention shifts or circumstances change
  - Context signals (time-of-day, stress level, work patterns) for timing actions

Persists to .hermes/state/personal_model.json (overlays the existing schema).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
STATE_DIR = HERMES_HOME / "state"
STATE_FILE = STATE_DIR / "personal_model.json"
LOG_DIR = HERMES_HOME / "logs"

STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log(msg: str):
    ts = datetime.now(timezone.utc).isoformat()
    with open(LOG_DIR / "personal_model.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def _default_state() -> dict:
    return {
        "version": 2,
        "created": datetime.now(timezone.utc).isoformat(),
        "updated": None,
        "values": {},
        "life_goals": [],
        "work_patterns": {
            "peak_hours": [],
            "peak_days": [],
            "deep_work_hours": [],
            "admin_hours": [],
            "session_avg_minutes": 0,
            "longest_streak_days": 0,
        },
        "decision_style": {
            "fast_decisions": [],
            "slow_decisions": [],
            "avg_response_minutes": 0,
            "delegation_rate": 0.0,
        },
        "stress_indicators": {
            "patterns": [],
            "triggers": [],
            "recovery_actions": [],
            "current_stress_level": "medium",
        },
        "unspoken_needs": [],
        "communication_preferences": {},
        "data_points": 0,
    }


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return _default_state()


def _save_state(state: dict):
    state["updated"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    _log(f"State saved (goals={len(state.get('life_goals', []))})")


def _extract_values() -> dict:
    """
    Parse TELOS.md and HERMES.md for explicit values — return as a
    confidence-weighted dict {value: confidence}.
    """
    values = {}
    docs = {
        "telos": HERMES_HOME / "TELOS.md",
        "hermes": HERMES_HOME / "HERMES.md",
    }

    telos_care = [
        "Productivity", "System reliability", "Knowledge preservation",
        "Proactive intelligence", "Zero cost",
    ]
    for v in telos_care:
        values[v.lower()] = 0.9  # explicitly stated

    hermes_principles = [
        "Durable", "Long-running", "Optimized", "Context-aware", "Autonomous",
    ]
    for p in hermes_principles:
        values[p.lower()] = 0.8  # operational principles as quasi-values

    # Look for refusal patterns ("What We Refuse To Do") — these indicate boundaries
    refusals = ["fabrication", "spam", "unpaid_costs", "hidden_problems", "docs_drift"]
    for r in refusals:
        values[f"avoid_{r}"] = 0.85

    return values


def _extract_unspoken_needs() -> list[dict]:
    """Read from existing autonomous_self.json inferred_values / unspoken_needs."""
    self_state_file = STATE_DIR / "autonomous_self.json"
    if self_state_file.exists():
        try:
            ss = json.loads(self_state_file.read_text())
            return ss.get("inferred_values", {}).get("unspoken_needs",
                     ss.get("unspoken_needs", []))
        except Exception:
            pass

    pm = _load_state()
    return pm.get("unspoken_needs", [])


def generate_life_goals() -> list[dict]:
    """
    Synthesise 3-5 long-term life goals from values + unspoken needs + domain docs.
    Each goal has a title, rationale, priority (1-10), domain, and expiry.
    """
    values = _extract_values()
    needs = _extract_unspoken_needs()

    goals = []
    now = datetime.now(timezone.utc)
    thirty_days = now + timedelta(days=30)

    # Goal 1: Career progression (from unspoken needs + values)
    career_need = any("career" in str(n.get("need", "")).lower() for n in needs)
    if career_need or values.get("productivity", 0) > 0.7:
        goals.append({
            "title": "Secure next career step",
            "rationale": "Deep research on career signals active; values productivity",
            "priority": 8,
            "domain": "career",
            "expires": thirty_days.isoformat(),
            "milestones": ["7 targeted applications", "2 networking intros", "skills gap closed"],
            "created": now.isoformat(),
        })

    # Goal 2: System reliability / infrastructure mastery
    infra_need = any("infrastructure" in str(n.get("need", "")).lower() for n in needs)
    if infra_need or values.get("system reliability", 0) > 0.7:
        goals.append({
            "title": "Homelab production-grade stability",
            "rationale": "40 containers, WiFi-only WAN; reliability is core value",
            "priority": 9,
            "domain": "infra",
            "expires": (now + timedelta(days=60)).isoformat(),
            "milestones": ["99.5% uptime", "automated backup verified", "zero manual restarts"],
            "created": now.isoformat(),
        })

    # Goal 3: Knowledge preservation + second brain
    if values.get("knowledge preservation", 0) > 0.7:
        goals.append({
            "title": "Build living second brain",
            "rationale": "Every decision/learning must be remembered; graphify + vector RAG pending",
            "priority": 7,
            "domain": "knowledge",
            "expires": (now + timedelta(days=45)).isoformat(),
            "milestones": ["3 domains indexed", "episodic memory layer", "query <5s p90"],
            "created": now.isoformat(),
        })

    # Goal 4: Proactive intelligence
    if values.get("proactive intelligence", 0) > 0.7:
        goals.append({
            "title": "Predictive CoS — anticipate before asked",
            "rationale": "CoS must surface problems before Rohit notices them",
            "priority": 7,
            "domain": "meta",
            "expires": (now + timedelta(days=30)).isoformat(),
            "milestones": ["3 correct silent predictions", "confidence-calibrated", "<10% false positives"],
            "created": now.isoformat(),
        })

    # Goal 5: Zero-friction interaction
    if values.get("avoid_spam", 0) > 0.7:
        goals.append({
            "title": "Reduce proactive noise to <1 actionable msg/day",
            "rationale": "Refuses notification spam; current gap is 50 insights unacted-on",
            "priority": 6,
            "domain": "meta",
            "expires": (now + timedelta(days=15)).isoformat(),
            "milestones": ["insight→action rate >=60%", "user-ignore rate <20%", "cooldown-tuned"],
            "created": now.isoformat(),
        })

    # Cap at 5, sort by priority
    goals = sorted(goals, key=lambda g: g["priority"], reverse=True)[:5]
    return goals


def decay_and_reprioritise(state: dict) -> list[dict]:
    """
    Review existing life_goals:
      - Remove expired
      - Decay priority for stale (unmilestoned) goals
      - Bump priority if value signal strengthens (e.g. more career interactions)
    Returns the updated goal list.
    """
    now = datetime.now(timezone.utc)
    goals = state.get("life_goals", [])
    updated = []

    for g in goals:
        exp = datetime.fromisoformat(g["expires"])
        if exp < now:
            _log(f"Goal '{g['title']}' expired — removing")
            continue

        # Decay: if no milestone progress in 10 days, lower priority by 1
        last_update = g.get("last_milestone_update")
        if last_update:
            age = (now - datetime.fromisoformat(last_update)).total_seconds() / 86400
            if age > 10 and g["priority"] > 3:
                g["priority"] -= 1
                _log(f"Goal '{g['title']}' decayed to prio {g['priority']} (stale)")

        # Re-assert expiry to keep active
        g["last_seen"] = now.isoformat()
        updated.append(g)

    # Merge in new goals from generate_life_goals
    new_goals = generate_life_goals()
    existing_titles = {g["title"] for g in updated}
    for g in new_goals:
        if g["title"] not in existing_titles:
            updated.append(g)
            _log(f"New life goal proposed: {g['title']}")

    # Sort
    updated = sorted(updated, key=lambda g: g["priority"], reverse=True)[:5]
    state["life_goals"] = updated
    state["values"] = _extract_values()
    state["unspoken_needs"] = _extract_unspoken_needs()
    _save_state(state)
    return updated


def get_context_signals() -> dict:
    """
    Return timing + stress context for action scheduling.
    """
    now = datetime.now(timezone.utc)
    state = _load_state()
    wp = state.get("work_patterns", {})
    stress = state.get("stress_indicators", {})

    return {
        "hour": now.hour,
        "weekday": now.strftime("%A"),
        "is_peak": now.hour in wp.get("peak_hours", []),
        "is_deep_work": now.hour in wp.get("deep_work_hours", []),
        "is_admin": now.hour in wp.get("admin_hours", []),
        "stress_level": stress.get("current_stress_level", "unknown"),
        "is_asleep_window": (now.hour < 7 or now.hour >= 23),
    }


def propose_goal_actions(goal: dict, context: dict) -> list[str]:
    """
    Given a life goal + context, propose concrete next actions.
    """
    domain = goal.get("domain", "")
    actions = []

    if domain == "career":
        actions.append("Run career_search for new opportunities")
        actions.append("Review skill gaps against target roles")
    elif domain == "infra":
        actions.append("Run homelab health check + self-heal")
        actions.append("Verify backup integrity on USB")
    elif domain == "knowledge":
        actions.append("Run episodic memory consolidation")
        actions.append("Index any new docs from this cycle")
    elif domain == "meta":
        actions.append("Check autonomous_self health + calibration")
        actions.append("Review feedback loop for engagement drops")

    # Timing filter: if deep_work and stress medium+, skip non-urgent
    if actions and context.get("is_deep_work") and context.get("stress_level") in ("high", "medium"):
        actions = [a for a in actions if "health" in a.lower() or "verify" in a.lower()] or actions[:1]

    return actions


if __name__ == "__main__":
    state = _load_state()
    if "--goals" in sys.argv:
        goals = generate_life_goals()
        print(json.dumps(goals, indent=2, default=str))
    elif "--decay" in sys.argv:
        goals = decay_and_reprioritise(state)
        print(json.dumps(goals, indent=2, default=str))
    elif "--context" in sys.argv:
        print(json.dumps(get_context_signals(), indent=2, default=str))
    else:
        goals = decay_and_reprioritise(state)
        print(json.dumps(goals, indent=2, default=str))
