#!/usr/bin/env python3
"""
evaluator.py — Rubric-based quality evaluation for pipeline outputs
Scores against criteria and tracks trends in ~/.hermes/evaluations/
"""

import json, os, pathlib, sys
from datetime import datetime

EVALS_DIR = pathlib.Path("/home/rohit/.hermes/evaluations")
INDEX_FILE = EVALS_DIR / "index.json"

RUBRICS = {
    "daily_digest": {
        "description": "Quality of daily homelab digest",
        "criteria": [
            {"name": "compactness", "weight": 0.25, "description": "No empty lines, under 500 chars, no markdown artifacts"},
            {"name": "completeness", "weight": 0.25, "description": "All sections present: containers, resources, fixes, discoveries, career"},
            {"name": "accuracy", "weight": 0.25, "description": "Container count matches reality, disk/mem numbers verified"},
            {"name": "delivery", "weight": 0.25, "description": "Telegram exact-match verified, no corruption"}
        ]
    },
    "troubleshoot": {
        "description": "Quality of container troubleshooting",
        "criteria": [
            {"name": "detection", "weight": 0.3, "description": "All unhealthy/exited containers found"},
            {"name": "fix_rate", "weight": 0.4, "description": "Successful fixes / total issues found"},
            {"name": "log_quality", "weight": 0.3, "description": "All actions logged with timestamps and results"}
        ]
    },
    "career_match": {
        "description": "Quality of career match recommendations",
        "criteria": [
            {"name": "relevance", "weight": 0.4, "description": "Score >= 3.0 matches are genuinely relevant"},
            {"name": "freshness", "weight": 0.3, "description": "At least one new match per day"},
            {"name": "actionability", "weight": 0.3, "description": "Each match includes company, score, and next step"}
        ]
    }
}

def init():
    EVALS_DIR.mkdir(parents=True, exist_ok=True)
    if not INDEX_FILE.exists():
        INDEX_FILE.write_text(json.dumps({"evaluations": [], "rubrics": RUBRICS}, indent=2))

def evaluate(target, rubric_name, scores, notes=None):
    init()
    index = json.loads(INDEX_FILE.read_text())
    rubric = RUBRICS.get(rubric_name)
    if not rubric:
        return {"error": f"Unknown rubric: {rubric_name}"}

    total = 0
    results = []
    for c in rubric["criteria"]:
        s = scores.get(c["name"], 0)
        if s < 0 or s > 100:
            return {"error": f"Score for {c['name']} must be 0-100"}
        results.append({"criterion": c["name"], "score": s, "weight": c["weight"], "weighted": s * c["weight"]})
        total += s * c["weight"]

    entry = {
        "target": target,
        "rubric": rubric_name,
        "score": round(total, 1),
        "results": results,
        "notes": notes,
        "timestamp": datetime.now().isoformat()
    }
    index["evaluations"].append(entry)
    INDEX_FILE.write_text(json.dumps(index, indent=2))
    return entry

def trend(rubric_name, limit=10):
    init()
    index = json.loads(INDEX_FILE.read_text())
    evals = [e for e in index["evaluations"] if e["rubric"] == rubric_name][-limit:]
    if not evals:
        return "No evaluations yet"
    scores = [e["score"] for e in evals]
    return {
        "rubric": rubric_name,
        "count": len(scores),
        "latest": scores[-1] if scores else None,
        "avg": round(sum(scores) / len(scores), 1) if scores else 0,
        "min": min(scores) if scores else 0,
        "max": max(scores) if scores else 0,
        "entries": [{"ts": e["timestamp"][:19], "score": e["score"], "target": e["target"]} for e in evals]
    }


if __name__ == "__main__":
    init()
    if len(sys.argv) < 2:
        print("Usage: evaluator.py [list|trend|eval] [rubric] [target]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "list":
        index = json.loads(INDEX_FILE.read_text())
        print("Available rubrics:")
        for name, r in RUBRICS.items():
            print(f"  {name}: {r['description']}")
        print(f"\nTotal evaluations: {len(index['evaluations'])}")
    elif cmd == "trend":
        rubric = sys.argv[2] if len(sys.argv) > 2 else "daily_digest"
        t = trend(rubric)
        if isinstance(t, dict):
            print(f"Trend for {rubric}:")
            print(f"  Latest: {t['latest']}, Avg: {t['avg']}, Range: {t['min']}-{t['max']}")
            for e in t["entries"]:
                print(f"  {e['ts']} {e['score']} {e['target']}")
        else:
            print(t)
    elif cmd == "eval":
        target = sys.argv[2] if len(sys.argv) > 2 else "manual"
        rubric = sys.argv[3] if len(sys.argv) > 3 else "daily_digest"
        print(f"Evaluate '{target}' with '{rubric}' rubric")
        print(f"Run: python3 evaluator.py score <target> <rubric> compactness=90 completeness=85 ...")
    else:
        print("Unknown command")