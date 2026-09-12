#!/usr/bin/env python3
"""Fix anticipation key access in mind_loop.py."""

with open("mind_loop.py", "r") as f:
    content = f.read()

# Fix: use .get() instead of direct dict access for anticipation action key
content = content.replace(
    'if ant["action"] == "verify_backups":',
    'if ant.get("action", "") == "verify_backups":',
)
content = content.replace(
    'elif ant["action"] == "send_morning_briefing":',
    'elif ant.get("action", "") == "send_morning_briefing":',
)
content = content.replace(
    'elif ant["action"] == "check_duckdns":',
    'elif ant.get("action", "") == "check_duckdns":',
)

with open("mind_loop.py", "w") as f:
    f.write(content)
print("Fixed anticipation key access in mind_loop.py")
