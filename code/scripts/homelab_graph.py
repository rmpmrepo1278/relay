"""
homelab_graph.py — CRG and graphify wrapper for homelab pipeline scripts.
Provides helper functions that wrap code-review-graph and graphify CLI calls,
returning structured data instead of raw text.

Multi-repo aware: all CRG functions accept an optional ``repo`` argument (an
alias like "hermes-agent", "hermes-scripts", "career-ops",
"home", or an absolute path). When omitted, they default to the hermes
graph and fall back to auto-detection from the current directory.
"""
import json, subprocess, os, sys, time
from pathlib import Path

CRG = os.environ.get("CRG_BIN", "/home/rohit/.local/bin/code-review-graph")
GRAPHIFY = os.environ.get("GRAPHIFY_BIN", "/home/rohit/.local/bin/graphify")
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
_REGISTRY = Path.home() / ".code-review-graph" / "registry.json"
_DEFAULT_REPO = str(HERMES_HOME)

def _registry():
    try:
        return json.loads(_REGISTRY.read_text()).get("repos", [])
    except Exception:
        return []

def _resolve_repo(repo):
    if not repo:
        return None
    for entry in _registry():
        if repo in (entry.get("alias"), entry.get("path")):
            return entry["path"]
    if str(repo).startswith("/"):
        return repo
    return None

def _crg_args(repo=None):
    path = _resolve_repo(repo)
    return ["--repo", path] if path else []

def _run(cmd, repo=None, timeout=30):
    try:
        if repo:
            cmd = list(cmd) + _crg_args(repo)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception:
        return -1, "", "command failed"

def run_cmd(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as exc:
        return -1, "", str(exc)

def crg_repos():
    return {"repos": [{"alias": e.get("alias"), "path": e["path"]} for e in _registry()]}

def crg_status(repo=None):
    rc, out, err = _run([CRG, "status"], repo=repo)
    if rc != 0:
        return {"error": err.strip() or out.strip()}
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
            data[k] = v
    return data

def crg_graph_health(stale_hours=48):
    """Return repos whose graph is empty or stale. Mirrors crg_helper.stale_repos."""
    now = time.time()
    unhealthy = []
    for entry in _registry():
        st = crg_status(entry["path"])
        if "error" in st:
            continue
        try:
            nodes = int(str(st.get("nodes", "0")).replace(",", ""))
        except (ValueError, TypeError):
            nodes = 0
        last_ts = None
        for key in ("last_updated", "last_updated"):
            if st.get(key):
                try:
                    last_ts = time.mktime(time.strptime(str(st[key]), "%Y-%m-%dT%H:%M:%S"))
                    break
                except (ValueError, TypeError):
                    continue
        stale = nodes == 0
        if last_ts is not None:
            stale = stale or (now - last_ts) / 3600 > stale_hours
        if stale:
            unhealthy.append({"alias": entry.get("alias"), "path": entry["path"],
                              "nodes": nodes, "last_updated": st.get("last_updated")})
    return unhealthy

def crg_impact(files, repo=None):
    if not files:
        return {"impact": "none", "affected_files": 0, "affected_components": []}
    file_list = " ".join(f'"{f}"' for f in files)
    rc, out, err = _run([CRG, "impact", "--files"] + list(files), repo=repo, timeout=30)
    if rc != 0:
        return {"error": err.strip() or out.strip()}
    affected = []
    for line in out.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("Analyzing") and not line.startswith("Impact"):
            affected.append(line)
    return {"impact": "high" if len(affected) > 10 else "medium" if affected else "low",
            "affected_files": len(affected), "affected_components": affected[:20]}

def crg_architecture(repo=None):
    rc, out, err = _run([CRG, "architecture"], repo=repo, timeout=30)
    if rc != 0:
        return {"error": err.strip() or out.strip()}
    return {"raw": out.strip()}

def crg_search(query, repo=None):
    rc, out, err = _run([CRG, "search", query], repo=repo, timeout=15)
    if rc != 0:
        return {"error": err.strip() or out.strip()}
    results = []
    for line in out.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("Searching"):
            results.append(line)
    return {"query": query, "results": results}

def crg_dead_code(repo=None):
    rc, out, err = _run([CRG, "dead-code"], repo=repo, timeout=30)
    if rc != 0:
        return {"error": err.strip() or out.strip()}
    items = []
    for line in out.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("Found") and not line.startswith("Dead"):
            items.append(line)
    return {"dead_code_count": len(items), "items": items[:30]}

def graphify_explain(node):
    rc, out, err = _run([GRAPHIFY, "explain", node], timeout=15)
    if rc != 0:
        return {"error": err.strip() or out.strip()}
    return {"node": node, "explanation": out.strip()}

def graphify_path(src, dst):
    rc, out, err = _run([GRAPHIFY, "path", src, dst], timeout=15)
    if rc != 0:
        return {"error": err.strip() or out.strip()}
    return {"source": src, "target": dst, "path": out.strip()}

def graphify_diagnose():
    rc, out, err = _run([GRAPHIFY, "diagnose", "multigraph", "--json"], timeout=15)
    if rc != 0:
        return {"error": err.strip() or out.strip()}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"raw": out.strip()}

def crg_detect_changes(repo=None):
    rc, out, err = _run([CRG, "detect-changes"], repo=repo, timeout=30)
    if rc != 0:
        return {"error": err.strip() or out.strip()}
    return {"raw": out.strip()}

def crg_query(query_str, repo=None):
    rc, out, err = _run([CRG, "query", query_str], repo=repo, timeout=15)
    if rc != 0:
        return {"error": err.strip() or out.strip()}
    return {"query": query_str, "results": out.strip()}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    repo = None
    if "--repo" in sys.argv:
        i = sys.argv.index("--repo")
        repo = sys.argv[i + 1]
    if cmd == "status":
        print(json.dumps(crg_status(repo), indent=2))
    elif cmd == "repos":
        print(json.dumps(crg_repos(), indent=2))
    elif cmd == "health":
        print(json.dumps(crg_graph_health(), indent=2))
    elif cmd == "impact" and len(sys.argv) > 2:
        print(json.dumps(crg_impact([a for a in sys.argv[2:] if a != "--repo" and a != repo], repo), indent=2))
    elif cmd == "architecture":
        print(json.dumps(crg_architecture(repo), indent=2))
    elif cmd == "search" and len(sys.argv) > 2:
        print(json.dumps(crg_search(sys.argv[2], repo), indent=2))
    elif cmd == "dead-code":
        print(json.dumps(crg_dead_code(repo), indent=2))
    elif cmd == "explain" and len(sys.argv) > 2:
        print(json.dumps(graphify_explain(sys.argv[2]), indent=2))
    elif cmd == "path" and len(sys.argv) > 3:
        print(json.dumps(graphify_path(sys.argv[2], sys.argv[3]), indent=2))
    elif cmd == "diagnose":
        print(json.dumps(graphify_diagnose(), indent=2))
    elif cmd == "detect-changes":
        print(json.dumps(crg_detect_changes(repo), indent=2))
    elif cmd == "query" and len(sys.argv) > 2:
        print(json.dumps(crg_query(sys.argv[2], repo), indent=2))
    else:
        print("Usage: homelab_graph.py <status|repos|health|impact|architecture|search|dead-code|explain|path|diagnose|detect-changes|query> [args...] [--repo <alias|path>]")