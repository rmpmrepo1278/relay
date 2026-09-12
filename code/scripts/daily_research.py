#!/usr/bin/env python3
"""
Daily Research Script for Homelab Improvements
Searches GitHub API for relevant repos and assesses impact.

Writes atomically via temp file + rename to prevent corruption
from concurrent cron overlaps or mid-write kills.
"""

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from homelab_graph import crg_status, crg_impact

RESULTS_FILE = Path.home() / ".hermes" / "research_results.json"

# Keywords that indicate transformational impact
TRANSFORM_KEYWORDS = ["AI", "LLM", "local", "self-hosted", "agent", "automation", "monitoring"]
SIGNIFICANT_KEYWORDS = ["docker", "container", "optimization", "performance", "dashboard"]


def assess_impact(repo):
    """Assess the potential impact of a repository"""
    desc = (repo.get("description") or "").lower()
    stars = repo.get("stargazers_count", 0)
    name = repo.get("full_name", "")

    # CRG blast-radius check
    blast = crg_impact([name]) if name else None
    blast_note = ""
    if blast and blast.get("impact") == "high":
        blast_note = " [high blast-radius]"
    elif blast and blast.get("impact") == "medium":
        blast_note = " [medium blast-radius]"

    # Transformational: High stars + AI/LLM keywords
    if stars > 100 and any(k in desc for k in ["LLM", "AI agent", "local AI", "self-hosted AI"]):
        return "transformational" + blast_note
    # Significant: Medium+ stars with relevant keywords
    if stars > 500 and any(k in desc for k in SIGNIFICANT_KEYWORDS):
        return "significant" + blast_note
    # Incremental: Lower stars or less relevant
    return "incremental" + blast_note


def run_search(query):
    """Run GitHub API search"""
    try:
        query_encoded = query.replace(" ", "+")
        cmd = f"curl -s 'https://api.github.com/search/repositories?q={query_encoded}&sort=stars&order=desc&per_page=5'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if "message" in data:
                print(f"GitHub API error for '{query}': {data['message']}")
                return None
            return data
        if result.stderr:
            print(f"Search stderr for '{query}': {result.stderr.strip()}")
    except json.JSONDecodeError as e:
        print(f"JSON parse error for '{query}': {e}")
    except subprocess.TimeoutExpired:
        print(f"Search timed out for '{query}'")
    except Exception as e:
        print(f"Search error for '{query}': {e}")
    return None


def atomic_json_write(path: Path, data):
    """Write JSON atomically: dump to temp file in same dir, then rename.

    Prevents corruption if the process is killed mid-write or if
    two cron instances overlap.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_path, path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def main():
    findings = []
    timestamp = datetime.now(timezone.utc).isoformat()

    # Search queries — keep focused to limit token burn
    # Each query returns 5 results, 4 queries = ~20 repos max to skim
    queries = [
        "LLM inference optimization speculative decoding",
        "self-hosted AI agent framework MCP",
        "homelab docker monitoring AI",
        "autonomous agent planning memory"
    ]

    for query in queries:
        results = run_search(query)
        if results and "items" in results:
            for item in results["items"]:
                findings.append({
                    "timestamp": timestamp,
                    "source": "github",
                    "category": "homelab",
                    "title": item.get("full_name", ""),
                    "description": item.get("description", "")[:200] if item.get("description") else "",
                    "url": item.get("html_url", ""),
                    "stars": item.get("stargazers_count", 0),
                    "language": item.get("language", ""),
                    "updated": item.get("updated_at", ""),
                    "impact": assess_impact(item)
                })

    # Load existing results
    if RESULTS_FILE.exists():
        try:
            with open(RESULTS_FILE) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, ValueError):
            print(f"WARNING: {RESULTS_FILE} is corrupt, starting fresh")
            existing = []
    else:
        existing = []

    # Append new findings
    existing.extend(findings)

    # Keep only last 100 findings
    existing = existing[-100:]

    # Atomic write — prevents corruption from concurrent runs or mid-write kills
    atomic_json_write(RESULTS_FILE, existing)

    # Verify the write was valid
    try:
        with open(RESULTS_FILE) as f:
            verified = json.load(f)
        assert isinstance(verified, list), "Verification failed: not a list"
    except Exception as e:
        print(f"ERROR: Verification of {RESULTS_FILE} failed: {e}")
        return findings

    # Graph stats
    graph = crg_status()
    graph_line = ""
    if isinstance(graph, dict) and "nodes" in graph:
        graph_line = f" | Graph: {graph.get('nodes', '?')} nodes, {graph.get('edges', '?')} edges"

    # Print summary by impact
    by_impact = {}
    for f in findings:
        by_impact[f["impact"]] = by_impact.get(f["impact"], 0) + 1

    print(f"Saved {len(findings)} new research findings{graph_line}")
    print(f"Impact breakdown: {by_impact}")

    return findings


if __name__ == "__main__":
    main()