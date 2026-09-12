"""
homelab_evaluator.py — Evaluates discovered candidates for deployment
Reads from discoveries.jsonl, scores against homelab constraints,
outputs decisions (deploy/skip/wait) to evaluations.jsonl
"""

import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path
from homelab_graph import crg_status, crg_impact

DATA_DIR = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
CACHE_FILE = DATA_DIR / "data" / "discoveries.jsonl"
EVAL_FILE = DATA_DIR / "data" / "evaluations.jsonl"
STATE_FILE = DATA_DIR / "data" / "discovery_state.json"

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_eval": None, "deployed": [], "skipped": [], "seen": []}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

def get_current_stack():
    """Return list of Docker images currently running"""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Image}}"],
            capture_output=True, text=True, timeout=10
        )
        return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
    except Exception as e:
        print(f"  Error getting Docker stack: {e}")
        return []

def get_resource_usage():
    """Return current resource usage summary"""
    usage = {}
    try:
        r = subprocess.run(["free", "-g"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().split("\n")
        mem = lines[1].split()
        usage["mem_total_gb"] = int(mem[1])
        usage["mem_used_gb"] = int(mem[2])
        usage["mem_pct"] = int(mem[2]) / int(mem[1]) * 100
    except: pass
    try:
        r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        parts = r.stdout.strip().split("\n")[1].split()
        usage["disk_pct"] = int(parts[4].rstrip("%"))
    except: pass
    return usage

def evaluate_candidate(candidate, stack, resources):
    """Return decision: deploy, skip, or wait with reason"""
    name = candidate.get("name", "")
    score = candidate.get("score", 0)
    topics = candidate.get("topics", [])
    desc = (candidate.get("description", "") + " " + name).lower()

    # Don't deploy if already in stack
    for img in stack:
        if name.split("/")[-1].lower() in img.lower():
            return {"decision": "skip", "reason": "already in stack"}

    # Resource check
    mem_pct = resources.get("mem_pct", 50)
    disk_pct = resources.get("disk_pct", 50)
    if mem_pct > 85:
        return {"decision": "wait", "reason": f"memory at {mem_pct:.0f}%"}
    if disk_pct > 85:
        return {"decision": "wait", "reason": f"disk at {disk_pct:.0f}%"}

    # CRG blast-radius check
    blast = crg_impact([name])
    if blast.get("impact") == "high":
        return {"decision": "wait", "reason": f"high blast-radius ({blast.get("affected_files", 0)} files affected)"}

    # Score-based
    if score < 50:
        return {"decision": "skip", "reason": f"low relevance score ({score})"}

    # MCP servers: always high priority
    if "mcp" in topics and score >= 50:
        return {"decision": "deploy", "reason": "MCP server with good relevance", "deploy_type": "mcp"}

    # Self-hosted tools that fill a gap
    gap_keywords = {
        "backup": not any("backup" in d.lower() for d in desc.split()),
        "monitoring": not any(mon in desc.lower() for mon in ["monitoring", "observability"]),
    }

    if "backup" in desc and gap_keywords.get("backup", True):
        return {"decision": "deploy", "reason": "fills backup gap", "deploy_type": "service"}
    if "monitoring" in desc or "observability" in desc:
        # We already have Prometheus/Grafana/Loki stack
        return {"decision": "skip", "reason": "monitoring stack already covered"}

    # Default for decent scores
    if score >= 70:
        return {"decision": "deploy", "reason": f"high relevance ({score})", "deploy_type": "service"}

    return {"decision": "wait", "reason": f"moderate score ({score}), no critical gap"}

def evaluate():
    state = load_state()
    if not CACHE_FILE.exists():
        print("No discoveries to evaluate")
        return []

    stack = get_current_stack()
    resources = get_resource_usage()
    # Graph context
    graph = crg_status()
    graph_note = f" | Graph: {graph.get("nodes", "?")} nodes, {graph.get("edges", "?")} edges" if isinstance(graph, dict) and "nodes" in graph else ""
    print(f"Evaluating candidates at {datetime.now().isoformat()}")
    print(f"  Stack: {len(stack)} images, Mem: {resources.get("mem_pct", "?"):.0f}%, "
          f"Disk: {resources.get("disk_pct", "?"):.0f}%{graph_note}")
    print(f"  Stack: {len(stack)} images, Mem: {resources.get('mem_pct', '?'):.0f}%, "
          f"Disk: {resources.get('disk_pct', '?'):.0f}%")

    decisions = []
    with open(CACHE_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            candidate = json.loads(line)
            name = candidate.get("name", "")
            if name in state.get("deployed", []) or name in state.get("skipped", []):
                continue

            result = evaluate_candidate(candidate, stack, resources)
            result["name"] = name
            result["candidate"] = candidate
            result["evaluated_at"] = datetime.now().isoformat()

            if result["decision"] == "deploy":
                state.setdefault("deployed", []).append(name)
            elif result["decision"] == "skip":
                state.setdefault("skipped", []).append(name)
            # "wait" stays in pending

            decisions.append(result)
            EVAL_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(EVAL_FILE, "a") as ef:
                ef.write(json.dumps(result) + "\n")

    save_state(state)
    print(f"  Evaluated {len(decisions)}: deploy={sum(1 for d in decisions if d['decision']=='deploy')}, "
          f"skip={sum(1 for d in decisions if d['decision']=='skip')}, "
          f"wait={sum(1 for d in decisions if d['decision']=='wait')}")
    return decisions

if __name__ == "__main__":
    decisions = evaluate()
    for d in decisions:
        print(f"  [{d['decision']:6s}] {d['name']}: {d['reason']}")
