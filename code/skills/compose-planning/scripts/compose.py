#!/usr/bin/env python3
"""Compose — multi-step plan decomposition and dispatch.

Takes a natural-language goal, asks Claude Code to decompose it into
2-3 sub-tasks (each assigned to a specialist), then dispatches the plan
via agent_orchestrator.dispatch_plan().

Usage:
  compose.py plan "<goal>" [--dry-run]       # Decompose + dispatch
  compose.py decompose "<goal>"              # Just show subtasks
  compose.py dispatch "<plan_json>"           # Dispatch a ready-made plan
"""
import json, sys, os, subprocess, argparse
from pathlib import Path
from datetime import datetime, timezone

HERMES_HOME = Path.home() / ".hermes"
CLAUDE_DELEGATE = HERMES_HOME / "hermes-agent" / "scripts" / "claude_code_delegate.py"

PROMPT = """
Decompose the following goal into 2-3 parallelizable sub-tasks.
Each sub-task should be assigned to one of these specialists:
- infra_analyst: Docker, systemd, servers, containers, health checks, disk/memory
- career_agent: Jobs, applications, research, resumes, interviews, networking
- knowledge_miner: Web research, articles, papers, knowledge extraction
- wellness_watcher: Calendar, meetings, stress, breaks, wellness

Output ONLY valid JSON, no prose. The format:
[{"assignee": "infra_analyst", "content": "sub-task description", "priority": 5, "confidence": 0.8}]

Goal: __GOAL__
"""

def call_claude(prompt, timeout=180):
    """Use claude_code_delegate.py to get LLM response."""
    env = {**os.environ, "CC_HEADLESS_TIMEOUT": str(timeout)}
    cmd = [
        sys.executable, str(CLAUDE_DELEGATE),
        "--task", prompt,
        "--mode", "headless",
        "--json",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+30, env=env)
        if r.returncode == 0:
            result = json.loads(r.stdout.strip())
            if result.get("status") == "completed":
                return result.get("summary", "").strip()
    except Exception:
        pass
    return None

def decompose(goal):
    """Ask Claude to decompose a goal into subtasks."""
    prompt = PROMPT.replace("__GOAL__", goal)
    response = call_claude(prompt)
    if not response:
        return None, "Failed to get LLM response for decomposition"

    # Parse JSON from the response
    try:
        subtasks = json.loads(response)
    except json.JSONDecodeError:
        # Try to extract JSON from code block
        if response.strip().startswith("```json"):
            response = response.strip()[7:]
        if response.strip().endswith("```"):
            response = response.strip()[:-3]
        try:
            subtasks = json.loads(response.strip())
        except json.JSONDecodeError:
            return None, f"Could not parse LLM output as JSON: {response[:200]}"

    if not isinstance(subtasks, list):
        return None, f"Expected list, got {type(subtasks)}"

    # Validate and enrich
    SPECIALISTS = {"infra_analyst", "career_agent", "knowledge_miner", "wellness_watcher"}
    validated = []
    for i, st in enumerate(subtasks):
        if not isinstance(st, dict):
            continue
        assignee = st.get("assignee", "knowledge_miner")
        if assignee not in SPECIALISTS:
            assignee = "knowledge_miner"

        # Convert content to a command-like task
        content = st.get("content", str(st))
        task_type = "command" if "run" in content.lower() or "check" in content.lower() else "task"

        validated.append({
            "assignee": assignee,
            "type": task_type,
            "command": content,
            "content": content,
            "priority": st.get("priority", 5),
            "confidence": st.get("confidence", 0.6),
            "depends_on": st.get("depends_on"),
        })

    return validated, None

def dispatch_plan(plan_content, dry_run=False):
    """Decompose and dispatch a plan."""
    plan = {"content": plan_content, "action": "add_task", "goal_domain": "meta", "confidence": 0.7}

    subtasks, err = decompose(plan_content)
    if err:
        return {"success": False, "error": err}

    if dry_run:
        return {"success": True, "dry_run": True, "subtasks": subtasks,
                "text": format_subtasks(subtasks)}

    # Import and dispatch via the orchestrator
    sys.path.insert(0, str(HERMES_HOME / "scripts"))
    try:
        import agent_orchestrator as ao
        results = ao.dispatch_plan(plan)
        summary = ao.reconcile_and_surface(results)

        text = format_subtasks(subtasks) + "\n\n" + format_results(results)
        return {"success": True, "subtasks": subtasks, "results": results,
                "summary": summary, "text": text}
    except Exception as e:
        return {"success": False, "error": str(e)}

def format_subtasks(subtasks):
    lines = ["📋 **Plan: Decomposed into subtasks**"]
    for i, st in enumerate(subtasks):
        assignee = st.get("assignee", "?")
        icon = {"infra_analyst": "🔧", "career_agent": "💼", "knowledge_miner": "📚", "wellness_watcher": "🧘"}.get(assignee, "•")
        lines.append(f"  {i+1}. {icon} `{assignee}`: {st.get('content', st.get('command',''))[:100]}")
    return "\n".join(lines)

def format_results(results):
    lines = ["\n📊 **Results:**"]
    for r in results:
        assignee = r.get("assignee", "?")
        status = r.get("status", "unknown")
        icon = "✅" if status in ("ok", "completed", "observed") else "⚠️" if status == "proposed" else "❌" if status in ("error", "timeout") else "⏳"
        lines.append(f"  {icon} {assignee}: {status}")
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Multi-step plan decomposition and dispatch")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="Decompose and dispatch a goal")
    p.add_argument("goal")
    p.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    p.set_defaults(func=lambda a: dispatch_plan(a.goal, dry_run=a.dry_run))

    p = sub.add_parser("decompose", help="Just decompose (no dispatch)")
    p.add_argument("goal")
    p.set_defaults(func=lambda a: _cmd_decompose(a))

    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))

def _cmd_decompose(args):
    subtasks, err = decompose(args.goal)
    if err:
        return {"success": False, "error": err}
    return {"success": True, "subtasks": subtasks, "text": format_subtasks(subtasks)}

if __name__ == "__main__":
    main()
