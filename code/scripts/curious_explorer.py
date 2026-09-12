#!/usr/bin/env python3
"""
curious_explorer.py — Curiosity-Driven Exploration for Hermes.

Goes BEYOND the interest model to surface unexpected connections and
things Rohit didn't know he'd care about.

While the proactive researcher searches for what Rohit is ALREADY interested in,
the curious explorer finds things at the INTERESTS of his interests — unexpected
connections, adjacent fields, contrarian takes, and serendipitous discoveries.

Strategy:
1. Take top interests and find ADJACENT topics he hasn't explored
2. Cross-pollinate: combine two unrelated interests to find novel intersections
3. Contrarian: find takes that challenge his current thinking
4. Serendipity: random high-quality finds from arXiv, HN, GitHub trending
5. "You might not know": things in his skill-adjacent space he hasn't seen

Usage:
    python3 curious_explorer.py              # Run exploration cycle
    python3 curious_explorer.py --dry-run    # Print, don't send
"""

from __future__ import annotations
import json
import os
import random
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
STATE_DIR = HERMES_HOME / "state"
DATA_DIR = HERMES_HOME / "data"
SEEN_FILE = STATE_DIR / "curious_seen.json"

STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_interest_profile() -> list:
    """Load the real interest profile from the interest model output."""
    profile_file = DATA_DIR / "interest_profile.json"
    if not profile_file.exists():
        return ["self_hosting", "ai_agents", "automation", "infrastructure", "llm_inference"]
    try:
        data = json.loads(profile_file.read_text())
        topics = data.get("topics", {})
        # Return sorted by weight descending
        return [t for t, w in sorted(topics.items(), key=lambda x: -x[1])] or []
    except (json.JSONDecodeError, OSError):
        return ["self_hosting", "ai_agents", "automation", "infrastructure", "llm_inference"]


def load_seen() -> set:
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except (json.JSONDecodeError, OSError):
        import re as _re
        text = SEEN_FILE.read_text(errors="replace")
        items = _re.findall(r'"((?:[^"\\]|\\.)*)"', text)
        SEEN_FILE.rename(SEEN_FILE.with_suffix(".corrupt"))
        return set(items)


def save_seen(seen: set):
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", dir=STATE_DIR, suffix=".tmp", delete=False)
    tmp.write(json.dumps(list(seen)[-500:]))  # keep last 500
    tmp.close()
    os.replace(tmp.name, SEEN_FILE)


def search_searxng(query: str, num_results: int = 5) -> list:
    """Search via SearXNG."""
    try:
        url = f"http://127.0.0.1:8118/search?q={urllib.parse.quote(query)}&format=json&num_results={num_results}"
        req = urllib.request.Request(url, headers={"User-Agent": "Hermes/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            return data.get("results", [])[:num_results]
    except Exception:
        return []


def get_arxiv_papers(category: str, max_results: int = 5) -> list:
    """Get recent arXiv papers in a category."""
    try:
        url = f"https://export.arxiv.org/api/query?search_query=cat:{category}&sortBy=submittedDate&sortOrder=descending&max_results={max_results}"
        req = urllib.request.Request(url, headers={"User-Agent": "Hermes/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            content = r.read().decode()
            # Simple XML parsing
            import xml.etree.ElementTree as ET
            root = ET.fromstring(content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            papers = []
            for entry in root.findall("atom:entry", ns)[:max_results]:
                papers.append({
                    "title": entry.find("atom:title", ns).text.strip().replace("\n", " ")[:120],
                    "url": entry.find("atom:id", ns).text,
                    "published": entry.find("atom:published", ns).text,
                    "summary": entry.find("atom:summary", ns).text.strip().replace("\n", " ")[:200],
                })
            return papers
    except Exception:
        return []


def get_github_trending() -> list:
    """Get trending GitHub repos."""
    try:
        url = "https://api.github.com/search/repositories?q=created:>2026-06-18&sort=stars&order=desc&per_page=10"
        req = urllib.request.Request(url, headers={"User-Agent": "Hermes/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            return [
                {
                    "name": item["full_name"],
                    "description": (item.get("description") or "")[:100],
                    "stars": item["stargazers_count"],
                    "url": item["html_url"],
                }
                for item in data.get("items", [])[:10]
            ]
    except Exception:
        return []


def find_adjacent_topics(interests: list) -> list:
    """Find topics adjacent to Rohit's interests that he hasn't explored."""
    adjacency_map = {
        "career_growth": ["leadership", "executive_presence", "personal_branding", "networking_strategy"],
        "self_hosting": ["nixos", "talos_linux", "k3s", "nomad", "incus", "home_assistant_advanced"],
        "programming": ["zig", "gleam", "ocaml", "formal_verification", "wasm"],
        "automation": ["n8n_advanced", "event_driven_architecture", "temporal_workflows", "dagster"],
        "infrastructure": ["ebpf", "service_mesh", "gitops_advanced", "chaos_engineering"],
        "ai_agents": ["multi_agent_systems", "agent_evaluation", "rlhf", "constitutional_ai", "mcp_protocol"],
        "llm_inference": ["vllm", "triton_inference", "speculative_decoding", "model_compression", "cuda_optimization"],
        "monitoring": ["opentelemetry", "pyr0metry", "ebpf_observability", "llm_observability", "anomaly_detection"],
        "security": ["zero_trust_networking", "hardening_guides", "crowdsec", "wazuh", "falco"],
        "research": ["ml_sys", "optimization_research", "distributed_training", "attention_mechanisms"],
        "privacy": ["federation", "differential_privacy", "on_device_ml", "encrypted_computation"],
    }

    adjacent = []
    for interest in interests[:3]:
        neighbors = adjacency_map.get(interest, [])
        if neighbors:
            # Pick one random adjacent topic he might not know
            topic = random.choice(neighbors)
            adjacent.append({
                "from_interest": interest,
                "adjacent_topic": topic,
                "query": f"{topic} 2026 overview getting started",
            })

    return adjacent


def find_cross_pollination(interests: list) -> list:
    """Find intersections between two unrelated interests."""
    if len(interests) < 2:
        return []

    # Pick two different interests
    pair = random.sample(interests[:4], 2)
    topic_a, topic_b = pair[0].replace("_", " "), pair[1].replace("_", " ")

    query = f"{topic_a} {topic_b} intersection"
    results = search_searxng(query, num_results=3)

    if results:
        return [{
            "intersection": f"{topic_a} × {topic_b}",
            "results": results[:2],
        }]
    return []


COLLAB_MEMORY = HERMES_HOME / "collaborator-memory"


def _log_to_journal(interests: list, sections: list):
    """Write curiosity findings into the collaborator memory journal."""
    journal_dir = COLLAB_MEMORY / "journal"
    if not journal_dir.exists():
        return
    today = datetime.now().strftime("%Y-%m-%d")
    journal_file = journal_dir / f"curiosity-{today}.md"

    entry_lines = []
    # Extract non-header lines
    for line in sections[2:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("Things you didn't"):
            entry_lines.append(line)

    if not entry_lines:
        return

    entry = "\n".join(entry_lines)

    try:
        subprocess.run(["git", "-C", str(COLLAB_MEMORY), "pull", "--rebase", "--autostash"],
                       capture_output=True, timeout=15)

        prefix = f"\n## Curiosity — {datetime.now().strftime('%H:%M UTC')}\nInterests: {', '.join(interests[:3])}\n\n"
        if journal_file.exists():
            existing = journal_file.read_text()
            journal_file.write_text(existing + prefix + entry + "\n")
        else:
            journal_file.write_text(f"# Curiosity Log — {today}\n\n{prefix}{entry}\n")

        subprocess.run(["git", "-C", str(COLLAB_MEMORY), "add", str(journal_file)],
                       capture_output=True, timeout=10)
        subprocess.run(["git", "-C", str(COLLAB_MEMORY), "commit", "-m", f"curiosity: {today} findings"],
                       capture_output=True, timeout=10)
        subprocess.run(["git", "-C", str(COLLAB_MEMORY), "push"],
                       capture_output=True, timeout=30)
    except Exception:
        pass


def run_exploration(dry_run: bool = False) -> str:
    """Run a full curiosity-driven exploration cycle."""
    seen = load_seen()
    interests = load_interest_profile()

    sections = []
    sections.append(f"🔮 **Curiosity Report** — {datetime.now().strftime('%b %d, %H:%M')}")
    sections.append("Things you didn't know you'd care about:\n")

    # 1. Adjacent topics
    adjacent = find_adjacent_topics(interests)
    for adj in adjacent[:2]:
        results = search_searxng(adj["query"], num_results=3)
        new_results = [r for r in results if r.get("url", "") not in seen]
        if new_results:
            sections.append(f"🌱 **Adjacent to {adj['from_interest'].replace('_', ' ')}:** {adj['adjacent_topic'].replace('_', ' ')}")
            for r in new_results[:2]:
                title = r.get("title", "")[:80]
                url = r.get("url", "")
                sections.append(f"  • {title}")
                sections.append(f"    {url}")
                seen.add(url)
            sections.append("")

    # 2. Cross-pollination
    cross = find_cross_pollination(interests)
    for c in cross:
        sections.append(f"🔀 **Intersection:** {c['intersection']}")
        for r in c["results"]:
            title = r.get("title", "")[:80]
            url = r.get("url", "")
            if url not in seen:
                sections.append(f"  • {title}")
                sections.append(f"    {url}")
                seen.add(url)
        sections.append("")

    # 3. arXiv deep cuts
    arxiv_categories = {
        "ai_agents": "cs.AI",
        "llm_inference": "cs.LG",
        "self_hosting": "cs.NI",
        "automation": "cs.SE",
        "infrastructure": "cs.DC",
        "monitoring": "cs.NI",
        "security": "cs.CR",
        "research": "cs.AI",
    }
    for interest, category in arxiv_categories.items():
        papers = get_arxiv_papers(category, max_results=3)
        new_papers = [p for p in papers if p.get("url", "") not in seen]
        if new_papers:
            sections.append(f"📄 **arXiv ({interest.replace('_', ' ')}):**")
            for p in new_papers[:2]:
                title = p.get("title", "")[:80]
                url = p.get("url", "")
                sections.append(f"  • {title}")
                sections.append(f"    {url}")
                seen.add(url)
            sections.append("")
            break  # only one arXiv section per cycle

    # 4. GitHub trending (filtered for relevance)
    trending = get_github_trending()
    relevant_trending = []
    relevance_kw = ["ai", "agent", "llm", "docker", "kubernetes", "rust", "self-host", "automation", "devops"]
    for repo in trending:
        text = f"{repo['name']} {repo['description']}".lower()
        if any(kw in text for kw in relevance_kw) and repo["stars"] > 100:
            relevant_trending.append(repo)

    if relevant_trending:
        sections.append(f"⭐ **Trending on GitHub:**")
        for repo in relevant_trending[:3]:
            sections.append(f"  • {repo['name']} ⭐{repo['stars']}")
            if repo["description"]:
                sections.append(f"    {repo['description'][:80]}")
            sections.append(f"    {repo['url']}")
            sections.append("")

    # 5. Serendipity: random HN comment with high engagement
    try:
        req = urllib.request.Request("https://hacker-news.firebaseio.com/v0/topstories.json")
        with urllib.request.urlopen(req, timeout=10) as r:
            ids = json.loads(r.read())
        # Pick a random one from top 30
        random_id = random.choice(ids[5:30])
        req2 = urllib.request.Request(f"https://hacker-news.firebaseio.com/v0/item/{random_id}.json")
        with urllib.request.urlopen(req2, timeout=10) as r2:
            story = json.loads(r2.read())
        if story.get("score", 0) > 50:
            sections.append(f"🎲 **Serendipity:**")
            sections.append(f"  • {story.get('title', '')[:100]}")
            sections.append(f"    {story.get('url', f'https://news.ycombinator.com/item?id={random_id}')}")
            sections.append(f"    ({story.get('score', 0)} points on HN)")
    except Exception:
        pass

    save_seen(seen)

    message = "\n".join(sections)

    # Only return if there's real content (more than just the header)
    content_lines = [l for l in sections[2:] if l.strip() and not l.startswith("Things you didn't know")]
    if not content_lines:
        return ""

    # Save results for orchestrator
    results = {
        "findings": [l for l in sections if l.strip() and not l.startswith("Things")],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "interests_used": interests,
    }
    results_file = DATA_DIR / "curious_explorer_results.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)
    results_file.write_text(json.dumps(results, indent=2))

    # Log findings to collaborator journal
    _log_to_journal(interests, sections)

    print(message)
    return message


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    msg = run_exploration(dry_run=dry_run)
    if not dry_run and not msg:
        print("No new curious findings this cycle.")
    elif not dry_run:
        print(f"Sent curiosity report ({len(msg)} chars)")
