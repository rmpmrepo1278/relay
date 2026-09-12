#!/usr/bin/env python3
"""assess_idea.py - Evaluate a business/automation idea for the homelab stack."""
import sys
import json

def assess_idea(input_text: str) -> str:
    result = {"idea": input_text, "assessment": {}}
    lower = input_text.lower()
    if "memory" in lower or "rag" in lower or "vector" in lower:
        result["assessment"] = {
            "novelty": "Medium - Neo4j agent-memory + Metronix already deployed",
            "overlap": "High overlap with existing memory systems",
            "effort": "Low-Medium if extending existing systems",
            "recommendation": "Extend Neo4j or Metronix rather than build new"
        }
    elif "search" in lower or "job" in lower or "career" in lower:
        result["assessment"] = {
            "novelty": "High - Not in current stack",
            "overlap": "Low overlap",
            "effort": "Medium (2-5 days)",
            "recommendation": "Good candidate for Hermes skill or agent"
        }
    elif "monitor" in lower or "alert" in lower or "health" in lower:
        result["assessment"] = {
            "novelty": "Medium - Extensive monitoring exists",
            "overlap": "High overlap with existing stack",
            "effort": "Low if extending existing systems",
            "recommendation": "Integrate with existing monitoring, do not duplicate"
        }
    elif "docker" in lower or "container" in lower or "deploy" in lower:
        result["assessment"] = {
            "novelty": "Medium - 55 containers already running",
            "overlap": "Check if similar container exists",
            "effort": "Low (docker compose pattern established)",
            "recommendation": "Add to existing compose stack if possible"
        }
    elif "agent" in lower or "llm" in lower or "ai" in lower:
        result["assessment"] = {
            "novelty": "Medium - Hermes agent stack exists",
            "overlap": "Check against existing Hermes skills/agents",
            "effort": "Medium (integrate with Hermes ecosystem)",
            "recommendation": "Build as Hermes skill or MCP server"
        }
    else:
        result["assessment"] = {
            "novelty": "Unknown - needs more context",
            "overlap": "Cannot determine without code review",
            "effort": "Unknown",
            "recommendation": "Analyze repo/code first, then reassess"
        }
    return json.dumps(result, indent=2)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: assess_idea.py <repo_url_or_description>")
        sys.exit(1)
    print(assess_idea(sys.argv[1]))
