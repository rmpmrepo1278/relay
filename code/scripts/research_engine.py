#!/usr/bin/env python3
"""Autonomous Research Engine — discovers, evaluates, and recommends
repos, articles, and tools for the homelab.

Discovery sources:
  - GitHub Trending (daily/weekly)
  - Hacker News (front page + Show HN)
  - Reddit (r/selfhosted, r/homelab, r/devops)
  - RSS feeds (via data-management merged service)

Pipeline:
  1. discover()  — fetch new items from all sources
  2. evaluate()  — score each item (relevance, maintenance, stack, novelty)
  3. recommend() — surface top-scoring items to Telegram
  4. approve()   — user approves → added to build tracker

Usage:
  research_engine.py discover     # Discover new items (cron daily)
  research_engine.py recommend    # Score + surface recommendations
  research_engine.py approve <id> # Mark item as approved
  research_engine.py status       # Show pending/recent recommendations
"""

import json, os, re, sys, time, urllib.request, urllib.error, subprocess as _sp
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from homelab_graph import crg_status, crg_impact, crg_architecture, crg_search

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/home/rohit/.hermes"))

# --- Telegram ---
_TG_TOKEN: str | None = None
_TG_CHAT: str | None = None

def _load_tg_config():
    global _TG_TOKEN, _TG_CHAT
    _TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    _TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_HOME_CHANNEL")
    if not _TG_TOKEN or not _TG_CHAT:
        env_file = HERMES_HOME / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    if k == "TELEGRAM_BOT_TOKEN":
                        _TG_TOKEN = v.strip(chr(34) + chr(39))
                    elif k in ("TELEGRAM_CHAT_ID", "TELEGRAM_HOME_CHANNEL"):
                        _TG_CHAT = v.strip(chr(34) + chr(39))
def _send_telegram(message: str, parse_mode: str = "Markdown"):
    if _TG_TOKEN is None:
        _load_tg_config()
    if not _TG_TOKEN or not _TG_CHAT:
        return False
    try:
        from telegram_bridge import send_telegram_markdown as _send
        _send(message)
        return True
    except Exception:
        return False

def _github_repo_meta(full_name: str) -> dict:
    """Fetch GitHub repo metadata via API as fallback when CRG has no match."""
    token = os.environ.get("GITHUB_API_KEY", "")
    if not token:
        env_file = HERMES_HOME / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    if k.strip() == "GITHUB_API_KEY":
                        token = v.strip(chr(34) + chr(39))
                        break
    if not token:
        return {}
    url = f"https://api.github.com/repos/{full_name}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "homelab-research-pipeline",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return {
                "stars": data.get("stargazers_count", 0),
                "forks": data.get("forks_count", 0),
                "language": data.get("language"),
                "description": (data.get("description") or "")[:300],
                "topics": data.get("topics", [])[:10],
                "updated_at": data.get("updated_at", ""),
                "license": (data.get("license") or {}).get("spdx_id") if data.get("license") else None,
                "open_issues": data.get("open_issues_count", 0),
                "url": data.get("html_url", ""),
            }
    except Exception:
        return {}



DATA_DIR = HERMES_HOME / "data" / "research"
DATA_DIR.mkdir(parents=True, exist_ok=True)

FINDINGS_FILE = DATA_DIR / "findings.jsonl"
SEEN_FILE = DATA_DIR / "seen.json"
APPROVED_FILE = DATA_DIR / "approved.json"
RECOMMENDATIONS_FILE = DATA_DIR / "recommendations.json"
SENT_FILE = DATA_DIR / "sent.json"

RECOMMENDATION_THRESHOLD = 50  # score out of 100

# --- State Management ---

def _load_json(path: Path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, Exception):
            return default or {}
    return default or {}

def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2))

def _load_seen() -> set:
    return set(_load_json(SEEN_FILE, []))

def _save_seen(seen: set):
    _save_json(SEEN_FILE, sorted(seen))

def _load_approved() -> list:
    return _load_json(APPROVED_FILE, [])

def _save_approved(approved: list):
    _save_json(APPROVED_FILE, approved)

def _load_sent() -> set:
    return set(_load_json(SENT_FILE, []))

def _save_sent(sent: set):
    _save_json(SENT_FILE, sorted(sent))

# --- Source: GitHub Trending ---

def _fetch_json(url: str, timeout: int = 15) -> Optional[dict | list]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None

def discover_github_trending() -> list[dict]:
    """Fetch daily trending repos via GitHub API."""
    items = []
    for lang in ["", "python", "typescript", "go", "rust"]:
        url = f"https://api.github.com/search/repositories?q=created:>{(datetime.now() - __import__('datetime').timedelta(days=7)).strftime('%Y-%m-%d')}+stars:>100&sort=stars&order=desc&per_page=10"
        if lang:
            url += f"+language:{lang}"
        data = _fetch_json(url)
        if data and "items" in data:
            for repo in data["items"]:
                items.append({
                    "type": "github",
                    "url": repo["html_url"],
                    "title": repo["full_name"],
                    "description": repo.get("description", "") or "",
                    "stars": repo.get("stargazers_count", 0),
                    "language": repo.get("language", ""),
                    "topics": repo.get("topics", []),
                    "updated_at": repo.get("updated_at", ""),
                    "open_issues": repo.get("open_issues_count", 0),
                    "license": repo.get("license", {}).get("spdx_id", "") if repo.get("license") else "",
                    "source": "github_trending",
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                })
    return items

def discover_hacker_news() -> list[dict]:
    """Fetch top HN stories + Show HN."""
    items = []
    data = _fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    if not data:
        return items
    for story_id in data[:30]:
        story = _fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
        if not story or not story.get("title"):
            continue
        title = story.get("title", "")
        url = story.get("url", f"https://news.ycombinator.com/item?id={story_id}")
        desc = story.get("text", "")[:300] or title
        # Focus on selfhosted, homelab, AI/ML, devops, tooling
        keywords_rx = re.compile(
            r"(docker|kubernetes|selfhost|self-host|homelab|devops|server|linux|"
            r"ai|ml|llm|agent|automation|monitoring|backup|database|proxy|"
            r"container|orchestrat|deploy|cli|terminal|git|ci/cd|opensource)", re.I
        )
        if not keywords_rx.search(title + " " + desc):
            continue
        items.append({
            "type": "hn",
            "url": url,
            "title": title,
            "description": desc[:200],
            "points": story.get("score", 0),
            "source": "hacker_news",
            "discovered_at": datetime.now(timezone.utc).isoformat(),
        })
    return items

def discover_reddit() -> list[dict]:
    """Fetch top posts from relevant subreddits."""
    items = []
    subreddits = ["selfhosted", "homelab", "devops", "docker", "linux", "selfhosting"]
    for sub in subreddits:
        data = _fetch_json(f"https://www.reddit.com/r/{sub}/hot.json?limit=10",
                           timeout=10)
        if not data or "data" not in data:
            continue
        for post in data["data"].get("children", []):
            p = post.get("data", {})
            items.append({
                "type": "reddit",
                "url": f"https://www.reddit.com{p.get('permalink', '')}",
                "title": p.get("title", ""),
                "description": p.get("selftext", "")[:200] or p.get("title", ""),
                "score": p.get("score", 0),
                "subreddit": f"r/{sub}",
                "source": f"reddit_{sub}",
                "discovered_at": datetime.now(timezone.utc).isoformat(),
            })
    return items

# --- Evaluation ---

# Tier 1: Exact stack match (high weight — directly usable)
STACK_KEYWORDS = {
    "pihole": 20, "paperless": 20, "paperless-ngx": 20, "immich": 20,
    "calibre": 20, "calibre-web": 20, "traefik": 18, "portainer": 18,
    "vaultwarden": 18, "homeassistant": 18, "home-assistant": 18,
    "searxng": 18, "searx": 18, "linkwarden": 18,
    "bookstack": 18, "healthchecks": 15, "watchtower": 15,
    "prometheus": 15, "grafana": 15, "nodered": 15, "node-red": 15,
    "n8n": 15, "authelia": 15, "authentik": 15,
    "openwebui": 15,
    # Agent/homelab management
    "hermes": 15, "mcp": 12, "model-context-protocol": 12,
    "homelab": 12,
}
# Tier 2: General homelab relevance
HOMELAB_KEYWORDS = [
    r"\bdocker\b", r"\bkubernetes\b", r"\bk8s\b", r"\bself.?host",
    r"\bhomelab\b", r"\bdevops\b", r"\bmonitoring\b", r"\bbackup",
    r"\bdatabase\b", r"\bproxy\b", r"\breverse.?proxy\b", r"\btraefik",
    r"\bnginx\b", r"\bprometheus\b", r"\bgrafana\b", r"\bcontainer",
    r"\bdeploy", r"\bcli\b", r"\bterminal\b", r"\bgit\b", r"\bci/cd",
    r"\brss\b", r"\bsearch\b", r"\bdns\b", r"\bvpn\b", r"\btunnel",
    r"\bauth\b", r"\bsso\b", r"\bldap\b", r"\bsecret\b", r"\bvault",
    r"\bautomation\b", r"\bpipeline\b", r"\bagent\b", r"\bllm\b",
    r"\bai\b", r"\bmachine.?learning\b", r"\bvector\b", r"\bembedding",
    r"\brag\b", r"\bdocument\b", r"\bpaperless\b", r"\bocr\b",
    r"\bebook\b", r"\bcalibre\b", r"\bimmich\b", r"\bphoto\b",
    r"\bmedia\b", r"\bstreaming\b", r"\bjellyfin\b", r"\bplex\b",
    r"\bdownload\b", r"\btorrent\b", r"\barr\b",
    r"\bpihole\b", r"\bad.?block", r"\bdns\b",
    r"\bportainer\b", r"\bdashboard",
    r"\bwireguard\b", r"\btailscale\b", r"\bnetworking",
    r"\bfirewall\b", r"\bids\b", r"\bps\b",
    r"\bcron\b", r"\bscheduler\b", r"\bqueue\b",
    r"\bredis\b", r"\bpostgres\b", r"\bmariadb\b", r"\bsqlite\b",
    r"\bopen.?source\b", r"\bself.?hosted\b",
]

def _match_keywords(text: str) -> list[str]:
    text_lower = text.lower()
    matches = []
    for kw_pat in HOMELAB_KEYWORDS:
        if re.search(kw_pat, text_lower):
            matches.append(kw_pat.strip("\\b"))
    return matches

def evaluate_item(item: dict) -> dict:
    title = item.get("title", "")
    desc = item.get("description", "")
    topics = item.get("topics", [])
    text = f"{title} {desc} {topics}"
    text_lower = text.lower()
    kw_matches = _match_keywords(text)

    score = 0

    # Tier 1: Stack match (0-40) — direct homelab relevance
    stack_score = 0
    for name, weight in STACK_KEYWORDS.items():
        if name.lower() in text_lower:
            stack_score += weight
    score += min(stack_score, 40)

    # Tier 2: General homelab relevance (0-20)
    relevance = min(len(kw_matches) * 4, 20)
    score += relevance

    # Popularity (0-20)
    stars = item.get("stars", 0) or 0
    points = item.get("points", 0) or item.get("score", 0) or 0
    popularity = min(stars / 200 * 3, 12) + min(points / 20, 8)
    score += min(popularity, 20)

    # Maintenance (0-15) — only for GitHub repos
    if item.get("type") == "github":
        updated = item.get("updated_at", "")
        if updated:
            try:
                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                days_since = (datetime.now(timezone.utc) - updated_dt).days
                if days_since < 14:
                    score += 15
                elif days_since < 60:
                    score += 10
                elif days_since < 180:
                    score += 5
            except ValueError:
                pass
        issues = item.get("open_issues", 0)
        if issues < 5 and stars > 200:
            score += 5

    # Source bonus (0-10)
    source_bonus = {
        "reddit_selfhosted": 10,
        "reddit_homelab": 10,
        "hacker_news": 8,
        "github_trending": 6,
    }
    score += source_bonus.get(item.get("source", ""), 4)

    # CRG graph context for GitHub repos
    graph_context = {}
    if item.get("type") == "github":
        title = item.get("title", "")
        blast = crg_impact([title])
        if blast and blast.get("impact"):
            graph_context["blast_radius"] = blast
        arch = crg_architecture()
        if arch and "raw" in arch:
            graph_context["architecture"] = arch["raw"][:200]
        search_results = crg_search(title.split("/")[-1] if "/" in title else title)
        if search_results and "results" in search_results and search_results["results"]:
            graph_context["graph_matches"] = search_results["results"][:5]
        else:
            repo_name = title.split("/")[-1] if "/" in title else title
            meta = _github_repo_meta(title)
            if meta:
                graph_context["github_metadata"] = meta

    item["_score"] = min(score, 100)
    item["_keywords"] = kw_matches + [k for k in STACK_KEYWORDS if k in text_lower][:3]
    item["_graph_context"] = graph_context
    item["_evaluated_at"] = datetime.now(timezone.utc).isoformat()
    return item

# --- Discovery Pipeline ---

def discover_all() -> list[dict]:
    seen = _load_seen()
    all_items = []

    print("  Discovering GitHub Trending...")
    for item in discover_github_trending():
        if item["url"] not in seen:
            all_items.append(item)
            seen.add(item["url"])

    print("  Discovering Hacker News...")
    for item in discover_hacker_news():
        if item["url"] not in seen:
            all_items.append(item)
            seen.add(item["url"])

    print("  Discovering Reddit...")
    for item in discover_reddit():
        if item["url"] not in seen:
            all_items.append(item)
            seen.add(item["url"])

    _save_seen(seen)
    return all_items

def save_findings(items: list[dict]):
    for item in items:
        with open(FINDINGS_FILE, "a") as f:
            f.write(json.dumps(item) + "\n")

def score_and_recommend() -> list[dict]:
    """Score all unscored findings and return top recommendations."""
    scored = []
    if FINDINGS_FILE.exists():
        with open(FINDINGS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                if "_score" not in item:
                    item = evaluate_item(item)
                scored.append(item)

    # Save updated scores
    with open(FINDINGS_FILE, "w") as f:
        for item in scored:
            f.write(json.dumps(item) + "\n")

    # Graph summary for recommendations
    graph = crg_status()
    graph_note = ""
    if isinstance(graph, dict) and "nodes" in graph:
        graph_note = f" | Graph: {graph.get('nodes', '?')} nodes, {graph.get('edges', '?')} edges"

    recommendations = [i for i in scored if i.get("_score", 0) >= RECOMMENDATION_THRESHOLD]
    recommendations.sort(key=lambda x: x.get("_score", 0), reverse=True)

    # Avoid re-recommending (approved)
    approved = _load_approved()
    approved_urls = {a["url"] for a in approved}
    pending = [r for r in recommendations if r["url"] not in approved_urls]

    # Avoid re-sending (already sent to Telegram)
    sent = _load_sent()
    pending = [r for r in pending if r["url"] not in sent]

    _save_json(RECOMMENDATIONS_FILE, pending[:15])
    return pending[:15]

def format_recommendations(items: list[dict], max_items: int = 5) -> str:
    """Format recommendations for Telegram."""
    if not items:
        return "No new recommendations right now. Check back tomorrow."

    lines = ["🔬 *Autonomous Research — Top Recommendations*\n"]
    for i, item in enumerate(items[:max_items], 1):
        t = item.get("type", "?")
        emoji = {"github": "📦", "hn": "📰", "reddit": "💬"}.get(t, "🔗")
        score = item.get("_score", 0)
        bar = "█" * (int(score) // 10) + "░" * (10 - int(score) // 10)
        title = item.get("title", "Untitled")
        desc = item.get("description", "")[:120]
        url = item.get("url", "")
        kw = ", ".join(item.get("_keywords", [])[:5])
        lines.append(
            f"{emoji} *{i}. {title}*\n"
            f"   Score: {score}/100 {bar}\n"
            f"   {desc}\n"
            f"   {url}\n"
            f"   Tags: {kw}\n"
        )
    lines.append(f"\n_{len(items)} total recommendations. Reply with research:approve <id> to build_")
    return "\n".join(lines)

def approve_item(item_id: int) -> Optional[dict]:
    """Mark an item as approved for building."""
    recs = _load_json(RECOMMENDATIONS_FILE, [])
    if item_id < 1 or item_id > len(recs):
        return None
    item = recs[item_id - 1]
    item["approved_at"] = datetime.now(timezone.utc).isoformat()
    approved = _load_approved()
    approved.append(item)
    _save_approved(approved)
    return item

def cmd_discover():
    print("🔍 Autonomous Research: Discovery Phase")
    items = discover_all()
    save_findings(items)
    print(f"  Found {len(items)} new items. Saved to {FINDINGS_FILE}")
    # Auto-score and show
    recs = score_and_recommend()
    print(format_recommendations(recs))
    # Send top recommendations to Telegram
    if recs:
        msg = format_recommendations(recs, max_items=3)
        msg += "\n\n_Reply: research:approve <id> to build_"
        ok = _send_telegram(msg)
        sent = _load_sent()
        for r in recs:
            sent.add(r["url"])
        _save_sent(sent)
        print(f"  Telegram: {'sent' if ok else 'failed'} ({len(recs)} recommendations, {len(sent)} unique sent)")

def cmd_recommend():
    print("🔬 Autonomous Research: Scoring & Recommendations")
    recs = score_and_recommend()
    print(format_recommendations(recs))

def cmd_approve(item_id: int):
    item = approve_item(item_id)
    if item:
        print(f"✅ Approved: {item.get('title')} ({item.get('url')})")
        print(f"  Added to build tracker. Ready to implement when you are.")
    else:
        print(f"❌ Invalid ID: {item_id}")

def cmd_status():
    recs = _load_json(RECOMMENDATIONS_FILE, [])
    approved = _load_approved()
    sent = _load_sent()
    total_findings = 0
    if FINDINGS_FILE.exists():
        with open(FINDINGS_FILE) as f:
            total_findings = sum(1 for _ in f)
    print(f"📊 Research Engine Status")
    print(f"  Total findings: {total_findings}")
    print(f"  Pending recommendations: {len(recs)}")
    print(f"  Approved: {len(approved)}")
    print(f"  Sent (unique): {len(sent)}")
    if approved:
        print(f"  Last approved:")
        for a in approved[-3:]:
            print(f"    ✅ {a.get('title')} ({a.get('approved_at', '?')[:10]})")
    if recs:
        print(f"\n  Top pending:")
        for r in recs[:3]:
            print(f"    {'📦' if r.get('type')=='github' else '📰'} [{r.get('_score',0)}] {r.get('title')[:60]}")

def cmd_clear_sent():
    _save_sent(set())
    print("Cleared sent-tracking set. All items eligible for re-sending.")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    if cmd == "discover":
        cmd_discover()
    elif cmd == "recommend":
        cmd_recommend()
    elif cmd == "notify":
        recs = score_and_recommend()
        if recs:
            msg = format_recommendations(recs, max_items=3)
            ok = _send_telegram(msg)
            sent = _load_sent()
            for r in recs:
                sent.add(r["url"])
            _save_sent(sent)
            print(f"Sent {len(recs)} recommendations to Telegram: {'ok' if ok else 'failed'}")
        else:
            print("No recommendations to send.")
    elif cmd == "approve" and len(sys.argv) > 2:
        cmd_approve(int(sys.argv[2]))
    elif cmd == "status":
        cmd_status()
    elif cmd == "clear-sent":
        cmd_clear_sent()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)

if __name__ == "__main__":
    main()
