#!/usr/bin/env python3
"""
autonomous_self.py — Hermes' self-model layer.

Provides:
  - run_self_reflection(): introspect on own performance, confidence, gaps
  - run_self_health(): compute self-health score from multiple signals
  - propose_self_goals(): derive internal improvement goals from reflection
  - get_confidence(action, context): confidence calibration before acting

This module persists to .hermes/state/autonomous_self.json.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

HERMES_HOME = Path.home() / ".hermes"
STATE_DIR = HERMES_HOME / "state"
LOG_DIR = HERMES_HOME / "logs"
STATE_FILE = STATE_DIR / "autonomous_self.json"

STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log(msg: str, level: str = "INFO"):
    ts = datetime.now(timezone.utc).isoformat()
    path = LOG_DIR / "autonomous_self.log"
    with open(path, "a") as f:
        f.write(f"[{ts}] [{level}] {msg}\n")


def _default_state() -> dict:
    return {
        "version": 2,
        "created": datetime.now(timezone.utc).isoformat(),
        "updated": None,
        "reflection_count": 0,
        "self_goals": [],
        "performance": {
            "predictions_made": 0,
            "predictions_correct": 0,
            "insights_generated": 0,
            "insights_acted_on": 0,
            "messages_sent": 0,
            "messages_acknowledged": 0,
            "errors_made": 0,
            "errors_recovered": 0,
            "confidence_calibration": {},
        },
        "disagreements": [],
        "known_limitations": [],
        "improvement_areas": [],
        "strengths": [],
        "inferred_values": {},
        "last_analysis": {
            "timestamp": None,
            "overall_health": "unknown",
            "strengths": [],
            "weaknesses": [],
            "recommendations": [],
        },
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
    _log(f"State saved (reflections={state['reflection_count']})")


def _load_mind_loop_state() -> dict:
    ml_file = STATE_DIR / "mind_loop.json"
    if ml_file.exists():
        try:
            return json.loads(ml_file.read_text())
        except Exception:
            pass
    return {}


def _load_feedback() -> dict:
    fb_file = HERMES_HOME / "data" / "feedback_loop.json"
    if fb_file.exists():
        try:
            return json.loads(fb_file.read_text())
        except Exception:
            pass
    return {"suggestions": [], "responses": [], "stats": {"by_type": {}}}


def _calibration_bucket(action: str) -> str:
    """Map an action or specialist agent name to a calibration bucket key."""
    # Specialist agent names (from agent_orchestrator.DISPATCH_TABLE)
    if "infra" in action:
        return "infra"
    if "career" in action:
        return "career"
    if "knowledge" in action or "research" in action:
        return "knowledge"
    if "wellness" in action:
        return "wellness"
    # Action-type patterns
    if action.startswith("send_telegram"):
        return "telegram"
    if "run_command" in action:
        return "infra"
    if "fetch" in action:
        return "research"
    if "schedule" in action or "calendar" in action:
        return "calendar"
    if "email" in action:
        return "email"
    return "general"


def get_confidence(action: str, context: dict | None = None) -> float:
    """
    Return a calibrated confidence score (0.0–1.0) for an action based on
    historical calibration data. Falls back to a neutral 0.6 if no history.
    """
    state = _load_state()
    cal = state["performance"]["confidence_calibration"]
    bucket = _calibration_bucket(action)
    data = cal.get(bucket)
    if not data or not data.get("total"):
        return 0.6
    correct = data.get("correct", 0)
    total = data.get("total", 1)
    return round(correct / total, 3)


def record_action_outcome(action: str, outcome: str, confidence: float | None = None):
    """
    Records the outcome of an action and updates confidence calibration.
    outcome ∈ {"success", "failure", "partial", "user_ignored", "user_ack"}
    """
    state = _load_state()
    bucket = _calibration_bucket(action)
    cal = state["performance"]["confidence_calibration"]
    data = cal.setdefault(bucket, {"total": 0, "correct": 0, "last_conf": 0.5})

    data["total"] += 1
    if outcome in ("success", "user_ack"):
        data["correct"] += 1
    if confidence is not None:
        data["last_conf"] = confidence

    # Track mismatches between confidence and reality for calibration quality
    if confidence is not None:
        if outcome in ("success", "user_ack") and confidence < 0.6:
            # Under-confident but right → note it
            pass
        if outcome in ("failure", "user_ignored") and confidence > 0.8:
            # Over-confident and wrong → flag
            state["performance"].setdefault("calibration_mispredictions", []).append({
                "action": action,
                "conf": confidence,
                "outcome": outcome,
                "ts": datetime.now(timezone.utc).isoformat(),
            })

    if outcome in ("success", "user_ack"):
        state["performance"]["errors_recovered"] = state["performance"].get("errors_recovered", 0) + 1
    elif outcome in ("failure", "partial", "user_ignored"):
        state["performance"]["errors_made"] = state["performance"].get("errors_made", 0) + 1

    _save_state(state)
    _log(f"Action outcome recorded: {bucket} → {outcome} (cal={data['correct']}/{data['total']})")


def check_retry_budget(action_type: str, max_retries: int = 3) -> dict:
    """
    Check if an action type has exceeded its retry/escalation budget.
    Returns {'allowed': bool, 'retries_used': N, 'budget': M}.
    """
    state = _load_state()
    budget = state.setdefault("retry_budgets", {})
    b = budget.setdefault(action_type, {"max": max_retries, "used": 0, "window_start": None})

    now = datetime.now(timezone.utc)
    # Reset window every 24 hours
    if b.get("window_start"):
        ws = datetime.fromisoformat(b["window_start"])
        if (now - ws).total_seconds() > 86400:
            b["used"] = 0
            b["window_start"] = now.isoformat()
    else:
        b["window_start"] = now.isoformat()

    return {
        "allowed": b["used"] < b["max"],
        "retries_used": b["used"],
        "budget": b["max"],
    }


def consume_retry(action_type: str) -> int:
    """Increment retry counter. Returns new count."""
    state = _load_state()
    budget = state.setdefault("retry_budgets", {})
    b = budget.setdefault(action_type, {"max": 3, "used": 0, "window_start": None})
    if b.get("window_start"):
        ws = datetime.fromisoformat(b["window_start"])
        if (datetime.now(timezone.utc) - ws).total_seconds() > 86400:
            b["used"] = 0
            b["window_start"] = datetime.now(timezone.utc).isoformat()
    else:
        b["window_start"] = datetime.now(timezone.utc).isoformat()
    b["used"] += 1
    _save_state(state)
    return b["used"]


def run_self_reflection() -> dict:
    """
    Run a reflection pass: inspect the mind_loop state, feedback ledger,
    and gap signals; produce a self-analysis dict with improvement recommendations.
    """
    state = _load_state()
    ml_state = _load_mind_loop_state()
    feedback = _load_feedback()

    state["reflection_count"] += 1

    perf = state["performance"]
    ml_insights = ml_state.get("insights", [])
    ml_goals = ml_state.get("goals", [])
    ml_actions = ml_state.get("action_history", [])

    # --- Performance metrics ---
    perf["insights_generated"] += len(ml_insights)
    perf["messages_sent"] = ml_state.get("messages_sent_count", perf["messages_sent"])
    perf["messages_acknowledged"] = feedback.get("stats", {}).get("acknowledged_total", 0)

    # Compute prediction accuracy
    if perf["predictions_made"] and perf["predictions_correct"]:
        perf["accuracy"] = round(perf["predictions_correct"] / perf["predictions_made"], 3)
    else:
        perf["accuracy"] = 0.0

    # --- Confidence calibration check ---
    cal = perf["confidence_calibration"]
    calibration_issues = []
    for bucket, data in cal.items():
        if data.get("total", 0) > 2:
            actual_rate = data["correct"] / data["total"]
            last_conf = data.get("last_conf", 0.5)
            delta = abs(actual_rate - last_conf)
            if delta > 0.3:
                calibration_issues.append({
                    "bucket": bucket,
                    "calibrated_conf": last_conf,
                    "actual_rate": round(actual_rate, 3),
                    "delta": round(delta, 3),
                })

    # --- Gap detection ---
    weaknesses = []
    strengths = []
    known_limitations = []
    recommendations = []

    # Check for stale goals (unacted-on > 2 cycles)
    stale_goals = [g for g in ml_goals if not _actions_for_goal(ml_actions, g.get("title", ""))]
    if stale_goals:
        weaknesses.append("Goals not translating into actions")
        recommendations.append("Implement plan-to-action verification for each goal")

    # Check for low message acknowledgment rate
    if perf["messages_sent"] > 0:
        ack_rate = perf["messages_acknowledged"] / perf["messages_sent"]
        if ack_rate < 0.1:
            weaknesses.append(f"Low user engagement ({ack_rate:.1%} of messages acknowledged)")
            recommendations.append("Reduce Telegram frequency; A/B test message framing")
        elif ack_rate > 0.5:
            strengths.append(f"High user engagement ({ack_rate:.1%} acknowledgment rate)")

    # Check for calibration issues
    if calibration_issues:
        known_limitations.append("Confidence calibration drift detected")
        recommendations.append("Re-weight confidence buckets; recalibrate using recent outcomes")

    # Check for insight-action gap
    acted_insights = [a for a in ml_actions if a.get("source") == "insight"]
    insight_gap = len(ml_insights) - len(acted_insights)
    if insight_gap > 5:
        weaknesses.append(f"{insight_gap} insights not acted upon — filter too noisy")
        recommendations.append("Tighten insight→action threshold; suppress low-signal insights")

    # Check for error recovery
    if perf["errors_made"] > 0 and perf["errors_recovered"] == 0:
        known_limitations.append("No error recovery demonstrated")
        recommendations.append("Add inline action verification + retry/compensate paths")

    # Check for diversity of domains in actions
    action_domains = {a.get("domain", "unknown") for a in ml_actions[-30:]}
    if len(action_domains) < 2:
        weaknesses.append("Narrow domain focus — only operating in limited areas")
        recommendations.append("Expand proactive engine to cross domains (career↔health↔knowledge)")

    # --- Values inference (lightweight) ---
    inferred = state["inferred_values"]
    # Infer communication style from feedback
    fb_stats = feedback.get("stats", {}).get("by_type", {})
    if fb_stats:
        low_eng_types = [t for t, s in fb_stats.items()
                        if s.get("total", 0) > 3 and s.get("clicked", 0) == 0]
        if low_eng_types:
            inferred["ignored_suggestion_types"] = low_eng_types
            recommendations.append(f"Avoid suggestion types: {', '.join(low_eng_types)}")

    # --- Self-goals generation ---
    self_goals = []
    if "Low user engagement" in str(weaknesses):
        self_goals.append({
            "title": "Improve engagement calibration",
            "detail": "Learn which message types Rohit acts on; reduce noise",
            "priority": 8,
            "created": datetime.now(timezone.utc).isoformat(),
            "expires": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        })
    if calibration_issues:
        self_goals.append({
            "title": "Fix confidence calibration drift",
            "detail": "Recalibrate confidence scores for each action bucket",
            "priority": 7,
            "created": datetime.now(timezone.utc).isoformat(),
            "expires": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        })
    if not ml_goals:
        self_goals.append({
            "title": "Establish personal long-term goals",
            "detail": "Synthesise 3-5 life goals from TELOS.md/SOP.md/facts.json",
            "priority": 9,
            "created": datetime.now(timezone.utc).isoformat(),
            "expires": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        })

    # Merge with existing self-goals, deduplicate by title
    existing_titles = {g["title"] for g in state["self_goals"]}
    for g in self_goals:
        if g["title"] not in existing_titles:
            state["self_goals"].append(g)

    overall_health = "excellent" if not weaknesses else "adequate" if len(weaknesses) <= 2 else "degraded"
    if calibration_issues and insight_gap > 10:
        overall_health = "poor"

    analysis = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_health": overall_health,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "known_limitations": known_limitations,
        "recommendations": recommendations,
        "self_goals_added": len(self_goals),
        "calibration_issues": calibration_issues,
        "accuracy": perf.get("accuracy", 0.0),
        "insight_action_gap": insight_gap,
    }

    state["last_analysis"] = analysis
    _save_state(state)
    _log(f"Self-reflection #{state['reflection_count']}: health={overall_health}, "
         f"strengths={len(strengths)}, weaknesses={len(weaknesses)}, "
         f"recommendations={len(recommendations)}")

    return {
        "overall_health": overall_health,
        "self_goals": state["self_goals"],
        "analysis": analysis,
    }


def run_self_health() -> dict:
    """
    Lightweight health check for Hermes itself — module availability,
    state file freshness, daemon liveness.
    """
    state = _load_state()
    issues = []

    # Check module availability
    mod_dir = HERMES_HOME / "scripts"
    required_modules = [
        "mind_loop.py",
        "insight_engine.py",
        "autonomous_fixer.py",
        "proactive_engine.py",
        "n8n_bridge_server.py",
    ]
    for mod in required_modules:
        if not (mod_dir / mod).exists():
            issues.append(f"Missing module: {mod}")

    # Check state freshness
    ml_state = _load_mind_loop_state()
    last_cycle = ml_state.get("last_cycle")
    if last_cycle:
        try:
            last_dt = datetime.fromisoformat(last_cycle.replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
            if age_min > 120:  # 2 hours
                issues.append(f"Mind loop stale ({age_min:.0f} min since last cycle)")
        except Exception:
            issues.append("Cannot parse last_cycle timestamp")
    else:
        issues.append("Mind loop has never run")

    # Check daemon liveness via PID file
    pid_file = STATE_DIR / "daemon_state.json"
    if pid_file.exists():
        try:
            ds = json.loads(pid_file.read_text())
            pid = ds.get("pid")
            if pid:
                try:
                    os.kill(pid, 0)
                except (ProcessLookupError, PermissionError):
                    issues.append(f"Daemon PID {pid} not running")
        except Exception:
            issues.append("Cannot read daemon state")
    else:
        issues.append("No daemon state file")

    health = "healthy" if not issues else "degraded"
    result = {
        "status": health,
        "issues": issues,
        "state_fresh": len(issues) == 0,
        "last_reflection": state.get("last_analysis", {}).get("timestamp"),
    }
    _log(f"Self-health check: {health} ({len(issues)} issues)")
    return result


def propose_self_goals() -> list[dict]:
    """
    Propose new internal improvement goals based on the latest analysis.
    """
    state = _load_state()
    analysis = state.get("last_analysis", {})
    recommendations = analysis.get("recommendations", [])

    goals = []
    for rec in recommendations[:3]:
        goals.append({
            "title": f"Self-improve: {rec[:60]}",
            "detail": rec,
            "priority": 6,
            "type": "self_improvement",
            "created": datetime.now(timezone.utc).isoformat(),
            "expires": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        })

    # Add goals from known limitations
    for lim in state.get("known_limitations", [])[:2]:
        goals.append({
            "title": f"Address: {lim[:60]}",
            "detail": lim,
            "priority": 5,
            "type": "limitation",
            "created": datetime.now(timezone.utc).isoformat(),
            "expires": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        })

    existing_titles = {g["title"] for g in state["self_goals"]}
    new_goals = [g for g in goals if g["title"] not in existing_titles]
    state["self_goals"].extend(new_goals)
    state["self_goals"] = state["self_goals"][-30:]  # keep last 30
    _save_state(state)

    return new_goals


def _actions_for_goal(actions: list[dict], goal_title: str) -> list[dict]:
    """Find actions associated with a goal title (case-insensitive substring)."""
    needle = goal_title.lower()
    return [a for a in actions if needle in str(a.get("description", "")).lower()]


if __name__ == "__main__":
    print(json.dumps(run_self_reflection(), indent=2, default=str))
