"""
homelab_discoverer.py — Autonomous discovery engine
Scans GitHub trending, awesome-selfhosted, MCP servers, and AI agent patterns.
Outputs JSONL candidates to ~/.hermes/data/discoveries.jsonl
Runs weekly via scheduler.
"""

import json, urllib.request, os, sys
from datetime import datetime
from pathlib import Path
from homelab_graph import crg_status, crg_architecture, crg_search

DATA_DIR = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
CACHE_FILE = DATA_DIR / "data" / "discoveries.jsonl"
STATE_FILE = DATA_DIR / "data" / "discovery_state.json"

SOURCES = {
    "github_trending": "https://api.github.com/search/repositories?q=stars:>100+language:python&sort=stars&order=desc&per_page=10",
}

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_run": None, "seen": [], "deployed": []}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

def fetch_json(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Hermes-Discoverer/1.0",
            "Accept": "application/vnd.github.v3+json"
        })
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except Exception as e:
        print(f"  Fetch fail {url}: {e}")
        return None

def score_repo(repo):
    name = (repo.get("name", "") + " " + repo.get("description", "")).lower()
    topics = " ".join(repo.get("topics", []))

    score = 0
    positive = ["self-hosted", "docker", "mcp", "ai-agent", "automation", "homelab",
                "monitoring", "telegram", "bot", "cli", "backup", "observability",
                "prometheus", "grafana", "analytics", "dashboard"]
    for kw in positive:
        if kw in name or kw in topics:
            score += 15

    negative = ["game", "social-media", "ecommerce", "cms", "blog", "wordpress", "forum"]
    for a in negative:
        if a in name:
            score -= 30

    stars = repo.get("stargazers_count", 0)
    if stars > 1000:
        score += 20
    elif stars > 500:
        score += 10

    updated = repo.get("updated_at", "")
    if updated:
        try:
            d = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            days = (datetime.now().astimezone() - d).days
            if days < 30:
                score += 15
            elif days < 90:
                score += 5
        except Exception:
            pass

    return min(100, max(0, score))

def discover():
    state = load_state()
    print(f"Discovery run at {datetime.now().isoformat()}")
    print(f"  Seen: {len(state['seen'])} repos, Deployed: {len(state['deployed'])}")
    candidates = []

    print("  Scanning GitHub...")
    data = fetch_json(SOURCES["github_trending"])
    if data and "items" in data:
        for repo in data["items"]:
            full_name = repo.get("full_name", "")
            if full_name in state["seen"] or full_name in state["deployed"]:
                continue
            s = score_repo(repo)
            if s >= 40:
                candidates.append({
                    "source": "github_trending",
                    "name": full_name,
                    "url": repo.get("html_url", ""),
                    "description": repo.get("description", ""),
                    "stars": repo.get("stargazers_count", 0),
                    "score": s,
                    "topics": repo.get("topics", []),
                    "discovered_at": datetime.now().isoformat(),
                    "status": "candidate"
                })

    print("  Scanning MCP servers...")
    mcp_url = "https://api.github.com/repos/modelcontextprotocol/servers/contents/src"
    try:
        req = urllib.request.Request(mcp_url, headers={
            "User-Agent": "Hermes-Discoverer/1.0"
        })
        mcp_data = json.load(urllib.request.urlopen(req, timeout=10))
        for item in mcp_data:
            if item.get("type") == "dir":
                name = "mcp/" + item["name"]
                if name not in state["seen"] and name not in state["deployed"]:
                    candidates.append({
                        "source": "mcp_servers",
                        "name": name,
                        "url": "https://github.com/modelcontextprotocol/servers/tree/main/src/" + item["name"],
                        "description": "MCP server: " + item["name"],
                        "stars": 0,
                        "score": 60,
                        "topics": ["mcp"],
                        "discovered_at": datetime.now().isoformat(),
                        "status": "candidate"
                    })
    except Exception as e:
        print(f"  MCP scan error: {e}")

    for c in candidates:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "a") as f:
            f.write(json.dumps(c) + "\n")
        state["seen"].append(c["name"])

    state["last_run"] = datetime.now().isoformat()
    save_state(state)
    print(f"  Found {len(candidates)} new candidates")
    return candidates

if __name__ == "__main__":
    candidates = discover()
    print(f"\nSummary: {len(candidates)} new discoveries")
    for c in candidates:
        desc = c['description'][:80]
        print(f"  [{c['score']:2d}] {c['name']}: {desc}")
