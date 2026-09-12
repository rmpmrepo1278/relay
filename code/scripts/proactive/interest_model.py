#!/usr/bin/env python3
"""interest_model.py — Learns what Rohit cares about from available signals.

Outputs a weighted interest profile to data/interest_profile.json.
Designed to run every 3-6 hours via the Hermes scheduler.

Sources (best-effort, each optional):
  - research_results.json — GitHub/arXiv findings
  - personal_model.json — learned work patterns
  - agent.log (Telegram conversations)
  - Session logs in sessions/
"""

import json
import re
import os
import gzip
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
LOGS_DIR = HERMES_HOME / "logs"
SESSIONS_DIR = HERMES_HOME / "sessions"
STATE_DIR = HERMES_HOME / "state"
PROFILE_FILE = DATA_DIR / "interest_profile.json"

TOPIC_KEYWORDS = {
    "ai_agents": ["agent", "autonomous", "mcp", "tool use", "function calling", "agentic"],
    "llm_inference": ["llm", "model", "inference", "transformer", "quantization", "ollama"],
    "self_hosting": ["self-host", "selfhost", "docker", "container", "homelab", "deploy"],
    "automation": ["automation", "pipeline", "ci/cd", "workflow", "scheduler", "cron"],
    "monitoring": ["monitor", "observability", "prometheus", "grafana", "alert", "metric"],
    "security": ["security", "vulnerability", "cve", "auth", "encryption", "firewall"],
    "career": ["job", "career", "interview", "resume", "linkedin", "recruit"],
    "research": ["paper", "arxiv", "research", "publication", "novel"],
    "infrastructure": ["infra", "kubernetes", "orchestration", "scal", "high avail"],
    "privacy": ["privacy", "pii", "gdpr", "data protection", "redact"],
}

DECAY_DAYS = 14


def load_json(path, default=None):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return default if default is not None else {}


def load_jsonl_lines(path, max_lines=200):
    lines = []
    try:
        with open(path) as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        lines.append({"raw": line})
    except (OSError, json.JSONDecodeError):
        pass
    return lines


def extract_topics(text):
    text_lower = text.lower()
    found = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        if count > 0:
            found[topic] = count
    return found


def score_from_research():
    score = {}
    data = load_json(RESEARCH_RESULTS := HERMES_HOME / "research_results.json", [])
    cutoff = datetime.now(timezone.utc) - timedelta(days=DECAY_DAYS)
    for item in data if isinstance(data, list) else []:
        ts = item.get("timestamp", "")
        try:
            item_time = datetime.fromisoformat(ts) if ts else datetime.min.replace(tzinfo=timezone.utc)
        except ValueError:
            item_time = datetime.min.replace(tzinfo=timezone.utc)
        if item_time < cutoff:
            continue
        topics = extract_topics(json.dumps(item))
        for t, count in topics.items():
            score[t] = score.get(t, 0) + count
    return score


def score_from_personal_model():
    score = {}
    pm = load_json(STATE_DIR / "personal_model.json", {})
    patterns = pm.get("work_patterns", {})
    interests = pm.get("inferred_interests", {})
    for topic, weight in interests.items():
        if isinstance(weight, (int, float)):
            score[str(topic).lower()] = weight * 0.5
    return score


def score_from_telegram():
    score = {}
    log_file = LOGS_DIR / "agent.log"
    if not log_file.exists():
        return score
    try:
        lines = []
        result = __import__("subprocess").run(
            ["grep", "-i", "inbound message", str(log_file)],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")[-100:]
        import subprocess
        for line in lines:
            topics = extract_topics(line)
            for t, count in topics.items():
                score[t] = score.get(t, 0) + count * 2
    except Exception:
        pass
    return score


def score_from_sessions():
    score = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=DECAY_DAYS)
    if not SESSIONS_DIR.exists():
        return score
    for fpath in sorted(SESSIONS_DIR.iterdir())[-10:]:
        try:
            lines = load_jsonl_lines(fpath, max_lines=50)
            for entry in lines:
                topics = extract_topics(json.dumps(entry))
                for t, count in topics.items():
                    score[t] = score.get(t, 0) + count * 0.3
        except Exception:
            pass
    return score


def build_profile():
    scores = {}
    sources_used = []

    for source_name, source_fn in [
        ("research", score_from_research),
        ("personal_model", score_from_personal_model),
        ("telegram", score_from_telegram),
        ("sessions", score_from_sessions),
    ]:
        try:
            source_scores = source_fn()
            if source_scores:
                sources_used.append(source_name)
                for topic, weight in source_scores.items():
                    scores[topic] = scores.get(topic, 0) + weight
        except Exception:
            pass

    total = sum(scores.values()) or 1
    profile = {
        "version": 2,
        "generated": datetime.now(timezone.utc).isoformat(),
        "sources": sources_used,
        "topics": {k: round(v / total * 100, 1) for k, v in sorted(scores.items(), key=lambda x: -x[1])},
    }
    profile["dominant"] = max(profile["topics"], key=profile["topics"].get) if profile["topics"] else "unknown"
    return profile


if __name__ == "__main__":
    profile = build_profile()
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(profile, indent=2))
    print(f"Interest profile: {profile['dominant']} ({len(profile['topics'])} topics)")
