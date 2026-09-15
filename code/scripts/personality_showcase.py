#!/usr/bin/env python3
"""personality_showcase.py — Weekly Sunday post of one Evolution Log line per agent to Jenny topic."""
import pathlib, json, urllib.request, os
HERMES_HOME=pathlib.Path.home() / ".hermes"
def get_evolution_line(agent):
    for cand in [HERMES_HOME / "agentbus" / "memory" / f"{agent}.md", HERMES_HOME / "collaborator-memory" / "memory" / f"{agent}.md"]:
        if cand.exists():
            txt=cand.read_text()
            if "## Evolution Log" in txt:
                # Get last non-empty line after Evolution Log
                section=txt.split("## Evolution Log",1)[1]
                lines=[l.strip() for l in section.split("\n") if l.strip().startswith("-")]
                if lines:
                    return lines[-1]
    return None

def showcase():
    agents=["jenny","finlay","housekeep","calendula","connector","baseplate","vault","courier","inference"]
    lines=["🎭 *Weekly Personality Showcase* — how your agents evolved:"]
    for agent in agents:
        line=get_evolution_line(agent)
        if line:
            lines.append(f"  • *{agent}*: {line}")
    text="\n".join(lines)
    print(text[:500])
    # Send to Jenny topic 10000 via bridge
    try:
        import json as J, urllib.request as R
        data=J.dumps({"text":text,"message_thread_id":10000}).encode()
        req=R.Request("http://127.0.0.1:9198/telegram-send", data=data, headers={"Content-Type":"application/json"})
        r=J.loads(R.urlopen(req, timeout=10).read().decode())
        print(f"sent: {r.get('status')}")
    except Exception as e:
        print(f"send failed: {e} (dry-run ok)")

if __name__=="__main__":
    showcase()
