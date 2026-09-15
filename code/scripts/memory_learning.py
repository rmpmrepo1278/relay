#!/usr/bin/env python3
"""memory_learning.py — Feedback handler: 👍/👎 on Telegram messages trains agent."""
import json, pathlib, re, sys
HERMES_HOME=pathlib.Path.home() / ".hermes"
def handle_feedback(text, thread_id=None):
    # Simple: if text contains 👍 or 👎, update the agent's playbook Evolution Log
    if "👍" in text or "👎" in text:
        # Extract agent name from thread_id via topic_map
        try:
            tmap=json.load(open(HERMES_HOME / "agentbus" / "topic_map.json"))
            agent_for_thread={v:k for k,v in tmap.items()}
            agent=agent_for_thread.get(thread_id, "unknown")
            # Find personality file
            for cand in [HERMES_HOME / "agentbus" / "memory" / f"{agent}.md", HERMES_HOME / "collaborator-memory" / "memory" / f"{agent}.md"]:
                if cand.exists():
                    txt=cand.read_text()
                    if "## Evolution Log" in txt:
                        feedback="positive" if "👍" in text else "negative"
                        note=f"- {__import__('datetime').date.today()}: Feedback {feedback} on '{text[:40]}' — will adjust"
                        cand.write_text(txt.rstrip()+"\n"+note+"\n")
                        print(f"memory-learning: {agent} {feedback}")
                        return True
        except Exception as e:
            print(f"memory-learning error: {e}")
    return False

if __name__=="__main__":
    # Test
    handle_feedback("Great job 👍", thread_id=10000)
    print("memory-learning test done")
