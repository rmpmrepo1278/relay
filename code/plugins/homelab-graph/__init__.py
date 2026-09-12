"""homelab-graph plugin — Auto-queries CRG/graphify for code-related Telegram commands.

Fires on pre_gateway_dispatch for commands like /deploy, /refactor, /optimize,
/evaluate, /discover. Runs CRG blast-radius analysis and injects graph context
into the event text so the LLM sees it before making decisions.
"""
import json, os, subprocess, sys, re
from pathlib import Path
from homelab_graph import _run

CRG = os.environ.get("CRG_BIN", "/home/rohit/.local/bin/code-review-graph")
GRAPHIFY = os.environ.get("GRAPHIFY_BIN", "/home/rohit/.local/bin/graphify")

CODE_COMMANDS = re.compile(
    r"(?i)^/(deploy|refactor|optimize|evaluate|discover|hdeploy|hrefactor|hoptimize|hevaluate|hdiscover)\b"
)

def crg_status():
    rc, out, err = _run([CRG, "status"], timeout=15)
    if rc != 0:
        return None
    data = {}
    for line in out.strip().split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip().lower().replace(" ", "_")
        v = v.strip()
        try:
            data[k] = int(v)
        except ValueError:
            try:
                data[k] = float(v)
            except ValueError:
                data[k] = v
    return data

def crg_impact(files):
    if not files:
        return None
    rc, out, err = _run([CRG, "impact", "--files"] + files, timeout=15)
    if rc != 0:
        return None
    affected = []
    for line in out.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("Analyzing") and not line.startswith("Impact"):
            affected.append(line)
    return {"impact": "high" if len(affected) > 10 else "medium" if affected else "low",
            "affected_files": len(affected), "affected_components": affected[:10]}

def crg_architecture():
    rc, out, err = _run([CRG, "architecture"], timeout=15)
    if rc != 0:
        return None
    return out.strip()

def crg_search(query):
    rc, out, err = _run([CRG, "search", query], timeout=10)
    if rc != 0:
        return None
    results = []
    for line in out.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("Searching"):
            results.append(line)
    return results

def graphify_explain(node):
    rc, out, err = _run([GRAPHIFY, "explain", node], timeout=10)
    if rc != 0:
        return None
    return out.strip()

def graphify_diagnose():
    rc, out, err = _run([GRAPHIFY, "diagnose", "multigraph", "--json"], timeout=10)
    if rc != 0:
        return None
    try:
        return json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return None

def analyze_command(text):
    cmd_match = CODE_COMMANDS.match(text.strip())
    if not cmd_match:
        return None
    cmd = cmd_match.group(1).lower()

    graph = crg_status()
    graph_line = ""
    if graph and "nodes" in graph:
        graph_line = f"Graph: {graph.get('nodes', '?')} nodes, {graph.get('edges', '?')} edges, {graph.get('files', '?')} files"

    blast = crg_impact(["."])
    blast_line = ""
    if blast and blast.get("impact"):
        blast_line = f"Current blast-radius: {blast.get('impact')} ({blast.get('affected_files', 0)} files)"

    arch = crg_architecture()
    arch_line = ""
    if arch:
        arch_lines = arch.split("\n")[:5]
        arch_line = "Architecture: " + " | ".join(l.strip() for l in arch_lines if l.strip())

    parts = [graph_line, blast_line, arch_line]
    context = " | ".join(p for p in parts if p)

    return {
        "command": cmd,
        "graph_context": context,
        "blast": blast,
        "architecture": arch[:300] if arch else None,
    }

def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", on_pre_gateway_dispatch)

def on_pre_gateway_dispatch(event, **kwargs):
    text = getattr(event, "text", "") or ""
    analysis = analyze_command(text)
    if not analysis:
        return None

    graph_context = analysis.get("graph_context", "")
    if not graph_context:
        return None

    augmented = text + "\n\n[Graph context: " + graph_context + "]"
    return {"action": "rewrite", "text": augmented}

if __name__ == "__main__":
    result = analyze_command("/deploy my-service")
    print(json.dumps(result, indent=2))
