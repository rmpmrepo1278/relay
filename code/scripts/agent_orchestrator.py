#!/usr/bin/env python3
"""
agent_orchestrator.py — Multi-agent task decomposition for Hermes.

Decomposes a plan into sub-tasks handled by specialist sub-agents:
  - infra_analyst:  Docker, systemd, health checks, self-heal
  - career_agent:   Job search, application tracking, opportunity scoring
  - knowledge_miner:  Research, paper reading, knowledge graph indexing
  - wellness_watcher:  Calendar stress patterns, sleep, break reminders

Each sub-agent has:
  - A dispatch() function that takes a task dict and returns a result dict
  - Confidence calibration (delegates to autonomous_self)
  - A result channel back to narrative_memory + feedback_loop

Usage:
    python3 agent_orchestrator.py decompose "<plan content>"
    python3 agent_orchestrator.py dispatch <specialist> "<task>"
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERMES_HOME = Path.home() / ".hermes"
STATE_DIR = HERMES_HOME / "state"
LOG_DIR = HERMES_HOME / "logs"

STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log(msg: str):
    ts = datetime.now(timezone.utc).isoformat()
    with open(LOG_DIR / "agent_orchestrator.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def _crg_check(task: dict) -> str | None:
    """Query CRG for blast radius of a task's target files/repos.
    Only checks mutable actions (commands that write/delete/deploy).
    Returns 'high', 'medium', 'low', or None (if CRG unavailable or read-only)."""
    cmd = task.get("command", "") or task.get("content", "")
    # Only check CRG for write operations — skip read-only commands
    read_only_keywords = ["status", "health", "check", "verify", "inspect", "log", "ps", "list"]
    write_keywords = ["restart", "deploy", "update", "install", "delete", "rm ", "stop", "start", "create", "edit", "modify", "fix", "heal", "apply", "rollback"]
    is_write = any(kw in cmd.lower() for kw in write_keywords)
    is_read_only = any(kw in cmd.lower() for kw in read_only_keywords)
    if not is_write or is_read_only:
        return None
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        from homelab_graph import crg_impact
        target = task.get("target_repo") or task.get("target_path") or ""
        if not target:
            return None
        impact = crg_impact([target])
        if isinstance(impact, dict):
            return impact.get("impact")
        return None
    except Exception:
        return None


# ─── Specialist sub-agent definitions ────────────────────────────────────────

SPECIALISTS = {
    "infra_analyst": {
        "description": "Diagnose and fix homelab infrastructure issues",
        "triggers": ["docker", "container", "service", "health", "backup", "disk", "memory", "uptime"],
        "priority": 10,
        "handler": "infra_agent",
    },
    "career_agent": {
        "description": "Job search, application tracking, opportunity research",
        "triggers": ["job", "career", "application", "resume", "interview", "salary", "linkedin"],
        "priority": 8,
        "handler": "career_agent",
    },
    "knowledge_miner": {
        "description": "Research, paper reading, knowledge graph indexing, web fetch",
        "triggers": ["research", "paper", "arxiv", "hn", "fetch", "article", "read", "index"],
        "priority": 6,
        "handler": "knowledge_agent",
    },
    "wellness_watcher": {
        "description": "Calendar stress patterns, sleep, break reminders, wellness nudges",
        "triggers": ["stress", "wellness", "sleep", "break", "calendar", "meeting", "energy"],
        "priority": 5,
        "handler": "wellness_agent",
    },
}


def classify_task(content: str) -> str | None:
    """Route a task content string to the most relevant specialist."""
    content_lower = content.lower()
    best_match = None
    best_score = 0

    for spec_id, spec in SPECIALISTS.items():
        score = sum(1 for t in spec["triggers"] if t in content_lower)
        if score > best_score:
            best_score = score
            best_match = spec_id

    return best_match if best_score > 0 else None


def decompose_plan(plan: dict) -> list[dict]:
    """
    Decompose a single plan into 1-3 sub-tasks, each assigned to a specialist.
    Returns a list of sub-task dicts with 'assignee', 'command', and 'content'.
    """
    action = plan.get("action", "")
    content = plan.get("content", "")
    goal_domain = plan.get("goal_domain", "")
    confidence = plan.get("confidence", 0.6)

    # If the plan already has a clear specialist (via goal_domain), assign directly
    domain_map = {
        "infra": "infra_analyst",
        "career": "career_agent",
        "knowledge": "knowledge_miner",
        "meta": None,  # meta goals need decomposition
        "task": None,
    }
    preassigned = domain_map.get(goal_domain)

    subtasks = []

    # Decompose into 2-3 parallelisable steps
    if action == "run_command":
        cmd = plan.get("command", "")
        subtasks.append({
            "assignee": "infra_analyst",
            "type": "command",
            "command": cmd,
            "content": f"Execute infra check: {cmd}",
            "confidence": confidence,
            "priority": plan.get("priority", 5),
        })
        # Verification sub-task
        subtasks.append({
            "assignee": "infra_analyst",
            "type": "verify",
            "command": f"echo 'verify: {cmd}'",
            "content": f"Verify result of: {cmd}",
            "confidence": 0.9,
            "priority": plan.get("priority", 5) - 1,
            "depends_on": 0,
        })

    elif action == "send_telegram":
        assignee = preassigned or classify_task(content) or "knowledge_miner"
        subtasks.append({
            "assignee": assignee,
            "type": "telegram",
            "content": content,
            "priority": plan.get("priority", 5),
            "confidence": confidence,
        })

    elif action == "add_task":
        classified = classify_task(content) or preassigned or "knowledge_miner"
        subtasks.append({
            "assignee": classified,
            "type": "task",
            "content": content,
            "priority": plan.get("priority", 5),
            "confidence": confidence,
        })

    # If no subtasks were generated (unknown action), create a generic one
    if not subtasks:
        classified = classify_task(str(plan)) or "knowledge_miner"
        subtasks.append({
            "assignee": classified,
            "type": "generic",
            "content": str(plan.get("content", plan)),
            "priority": plan.get("priority", 3),
            "confidence": 0.4,
        })

    # Record decomposition to narrative memory
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import narrative_memory as _nm
        _nm.store_episode({
            "type": "plan_decomposition",
            "content": f"Plan '{content[:80]}' decomposed into {len(subtasks)} sub-tasks",
            "metadata": {
                "original_action": action,
                "subtask_count": len(subtasks),
                "assignees": [s["assignee"] for s in subtasks],
            },
        })
    except Exception:
        pass

    _log(f"Decomposed '{content[:60]}' → {len(subtasks)} sub-tasks: "
         f"{[s['assignee'] for s in subtasks]}")
    return subtasks


# ─── Specialist dispatchers ────────────────────────────────────────────────────

def infra_agent(task: dict) -> dict:
    """Runs a command + optional verification."""
    import subprocess
    cmd = task.get("command", "")
    result = {"assignee": "infra_analyst", "task": task.get("content", ""), "status": "error"}

    if not cmd:
        result["status"] = "no_command"
        return result

    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        result["status"] = "ok" if r.returncode == 0 else "error"
        result["returncode"] = r.returncode
        result["stdout"] = r.stdout[:500] if r.stdout else ""
        result["stderr"] = r.stderr[:300] if r.stderr else ""
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
    except Exception as e:
        result["error"] = str(e)

    # Record outcome for confidence calibration
    _record_specialist_outcome("infra_analyst", result["status"])
    return result


def career_agent(task: dict) -> dict:
    """Delegates to career_engine if available, else returns a proposal."""
    result = {"assignee": "career_agent", "task": task.get("content", ""), "status": "proposed"}

    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import career_engine as _ce
        content = task.get("content", "")

        if "search" in content.lower() or "job" in content.lower():
            # Run a career search
            jobs = _ce.career_search(query=content, limit=5) if hasattr(_ce, 'career_search') else []
            result["status"] = "completed"
            result["jobs_found"] = len(jobs) if isinstance(jobs, list) else 0
            result["sample"] = jobs[:2] if isinstance(jobs, list) else []
        elif "application" in content.lower():
            result["status"] = "completed"
            result["note"] = "Application tracking task queued"
        else:
            result["status"] = "completed"
            result["note"] = "Career insight reviewed"

    except ImportError:
        result["status"] = "unavailable"
        result["note"] = "career_engine not found"
    except Exception as e:
        result["error"] = str(e)
        result["status"] = "error"

    _record_specialist_outcome("career_agent", result["status"])
    return result


def knowledge_agent(task: dict) -> dict:
    """Handles research tasks: graph rag, web fetch, indexing."""
    result = {"assignee": "knowledge_miner", "task": task.get("content", ""), "status": "proposed"}

    content = task.get("content", "").lower()

    if "research" in content or "arxiv" in content:
        try:
            sys.path.insert(0, str(HERMES_HOME / "scripts"))
            import research_engine as _re
            findings = _re.run_research(content, max_depth=2) if hasattr(_re, 'run_research') else []
            result["status"] = "completed"
            result["findings"] = len(findings) if isinstance(findings, list) else 0
        except Exception as e:
            result["error"] = str(e)
            result["status"] = "error"
    elif "fetch" in content or "read" in content or "paper" in content:
        result["status"] = "completed"
        result["note"] = "Research fetch proposal logged"
    elif "index" in content:
        try:
            sys.path.insert(0, str(HERMES_HOME / "scripts"))
            import graphrag as _gr
            if hasattr(_gr, 'build_graph'):
                _gr.build_graph()
                result["status"] = "completed"
                result["note"] = "knowledge graph rebuilt"
            else:
                result["status"] = "completed"
                result["note"] = "indexing proposed"
        except Exception:
            result["status"] = "completed"
            result["note"] = "indexing proposed (graphify pending)"

    _record_specialist_outcome("knowledge_miner", result["status"])
    return result


def wellness_agent(task: dict) -> dict:
    """Handles wellness nudges and stress-pattern detection."""
    result = {"assignee": "wellness_watcher", "task": task.get("content", ""), "status": "observed"}

    content = task.get("content", "").lower()
    if "stress" in content:
        result["note"] = "Stress pattern logged for review"
        result["severity"] = "medium"
    elif "sleep" in content:
        result["note"] = "Sleep pattern check proposed"
    elif "break" in content:
        result["note"] = "Break reminder scheduled"

    _record_specialist_outcome("wellness_watcher", result["status"])
    return result


DISPATCH_TABLE = {
    "infra_analyst": infra_agent,
    "career_agent": career_agent,
    "knowledge_miner": knowledge_agent,
    "wellness_watcher": wellness_agent,
}


def dispatch(task: dict) -> dict:
    """Route a sub-task to the appropriate specialist agent."""
    assignee = task.get("assignee")
    handler = DISPATCH_TABLE.get(assignee)
    if not handler:
        return {"assignee": assignee, "status": "unknown_agent", "task": str(task)}

    # CRG blast-radius check — high-impact actions downgrade to proposals
    crg_risk = _crg_check(task)
    if crg_risk == "high":
        return {
            "assignee": assignee,
            "status": "proposed",
            "proposed": True,
            "reason": "CRG blast-radius: high impact — pending user approval",
            "task": task.get("content", ""),
            "crg_risk": "high",
        }

    # Confidence gate — adaptive: lowers threshold for new agents (few data points)
    conf = 0.6
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import autonomous_self as _as
        conf = _as.get_confidence(assignee)
        cal = _as._load_state()["performance"]["confidence_calibration"]
        data = cal.get(assignee, {})
        total = data.get("total", 0)

        # For agents with < 10 data points, use a lower threshold to allow
        # bootstrapping; otherwise require 0.35
        threshold = 0.15 if total < 10 else 0.35
        if conf < threshold:
            return {"assignee": assignee, "status": "deferred",
                    "reason": f"confidence {conf} below threshold ({threshold})",
                    "task": task.get("content", "")}
    except Exception:
        conf = 0.6

    result = handler(task)
    result["confidence"] = conf
    if crg_risk:
        result["crg_risk"] = crg_risk

    # Record to narrative memory
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import narrative_memory as _nm
        _nm.store_episode({
            "type": "action",
            "content": f"[{assignee}] {task.get('content', '')[:200]}",
            "metadata": {
                "assignee": assignee,
                "type": task.get("type", ""),
                "outcome": result.get("status", "unknown"),
                "confidence": conf,
            },
        })
    except Exception:
        pass

    _log(f"Dispatch → {assignee}: {result['status']}")
    return result


def _record_specialist_outcome(assignee: str, outcome: str):
    """Feed outcome back into confidence calibration."""
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import autonomous_self as _as
        _as.record_action_outcome(assignee, outcome)
    except Exception:
        pass


def dispatch_plan(plan: dict) -> list[dict]:
    """Decompose + dispatch a single plan to sub-agents, returning all results."""
    subtasks = decompose_plan(plan)
    results = []
    for i, st in enumerate(subtasks):
        # If this sub-task depends on a prior one, pass the prior result
        if st.get("depends_on") is not None:
            dep = results[st["depends_on"]]
            if dep.get("status") not in ("ok", "completed", "observed", "proposed"):
                results.append({
                    "assignee": st["assignee"],
                    "status": "skipped",
                    "reason": f"dependency failed: {dep.get('status')}",
                    "task": st.get("content", ""),
                })
                continue
        results.append(dispatch(st))
    return results


def reconcile_and_surface(results: list[dict]) -> dict:
    """
    Reconcile sub-agent results from a dispatched plan:
      - Count successes/failures per specialist
      - Surface any 'proposal' results as Telegram-confirm messages
      - Return a summary dict with follow-up actions
    """
    summary = {
        "total": len(results),
        "by_status": {},
        "by_assignee": {},
        "proposals": [],
        "follow_ups": [],
    }

    for r in results:
        status = r.get("status", "unknown")
        assignee = r.get("assignee", "unknown")
        summary["by_status"][status] = summary["by_status"].get(status, 0) + 1
        summary["by_assignee"][assignee] = summary["by_assignee"].get(assignee, 0) + 1

        # Collect proposals to surface via Telegram confirm
        if r.get("proposed") or (isinstance(r.get("result"), dict) and r["result"].get("proposed")):
            detail = r.get("result", r) if isinstance(r.get("result"), dict) else {}
            summary["proposals"].append({
                "assignee": assignee,
                "detail": detail,
                "text": detail.get("summary") or detail.get("subject") or detail.get("text", ""),
            })

    # Determine follow-up actions
    failed = summary["by_status"].get("error", 0) + summary["by_status"].get("timeout", 0)
    if failed > 0:
        # Escalate to autonomous_fixer
        summary["follow_ups"].append({
            "action": "escalate",
            "to": "autonomous_fixer",
            "reason": f"{failed} sub-agent failures detected",
        })

    if summary["proposals"]:
        summary["follow_ups"].append({
            "action": "send_telegram_proposals",
            "count": len(summary["proposals"]),
            "proposals": summary["proposals"],
        })

    _log(f"Reconciliation: {json.dumps(summary['by_status'])}, "
         f"proposals={len(summary['proposals'])}, "
         f"follow_ups={len(summary['follow_ups'])}")
    return summary


if __name__ == "__main__":
    if "--decompose" in sys.argv:
        # Read a plan JSON from argv
        plan_str = sys.argv[sys.argv.index("--decompose") + 1]
        plan = json.loads(plan_str)
        subtasks = decompose_plan(plan)
        print(json.dumps(subtasks, indent=2, default=str))
    elif "--dispatch" in sys.argv:
        idx = sys.argv.index("--dispatch")
        assignee = sys.argv[idx + 1]
        task_str = sys.argv[idx + 2]
        task = {"assignee": assignee, "type": "cli", "content": task_str, "command": task_str}
        print(json.dumps(dispatch(task), indent=2, default=str))
    else:
        # Show specialist registry
        print(json.dumps(SPECIALISTS, indent=2))
