#!/usr/bin/env python3
"""Fix plan_intelligence function to handle missing keys safely."""

with open("mind_loop_integration.py", "r") as f:
    content = f.read()

# Fix 1: Use .get() for action['action'] access (direct dict access is unsafe)
content = content.replace(
    "\"action\": f\"intelligent_{action['action']}\"",
    "\"action\": f\"intelligent_{action.get('action', 'task')}\"",
)

# Fix 2: Also fix content and priority access from suggested_actions
content = content.replace(
    """            "content": action["reason"],
            "priority": action["priority"],""",
    """            "content": action.get("reason", ""),
            "priority": action.get("priority", "medium"),""",
)

# Fix 3: Add safety wrapper to ensure all plans have required keys before returning
old_return = """    return plans


def act_intelligence(plan, context=None):"""
new_return = """    # Safety: ensure all plans have required keys
    safe_plans = []
    for p in plans:
        if not isinstance(p, dict):
            continue
        safe_p = {
            "action": p.get("action", "generic"),
            "content": p.get("content", ""),
            "priority": p.get("priority", "medium"),
        }
        # Preserve extra keys (like simulation data)
        for key in ("simulation", "goal_id", "reason", "source_insight"):
            if key in p:
                safe_p[key] = p[key]
        safe_plans.append(safe_p)

    return safe_plans


def act_intelligence(plan, context=None):"""

if old_return in content:
    content = content.replace(old_return, new_return)
    print("Added safety wrapper to return statements")
else:
    print("WARNING: Could not find the return pattern to replace!")

# Fix 4: Wrap goal_engine.suggestions access in .get() too
content = content.replace(
    """                "action": s["action"],
                "content": s.get("title", s.get("reason", "")),
                "priority": "medium",""",
    """                "action": s.get("action", "generic"),
                "content": s.get("title") or s.get("reason") or "",
                "priority": "medium",""",
)

with open("mind_loop_integration.py", "w") as f:
    f.write(content)
print("Fixed plan_intelligence function")
