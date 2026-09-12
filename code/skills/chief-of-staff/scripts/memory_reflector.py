#!/usr/bin/env python3
"""
memory_reflector.py — Self-Evolving Memory System

Automatically reflects on conversations and saves learnings to ClaudeMem.
This makes Hermes "get smarter the more you use it" — like QwenPaw's
memory-evolving capability.

Runs as a cron job (every 6 hours) and after significant conversations.

Usage:
    python3 memory_reflector.py [--since="1 hour ago"] [--json]
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
CLAUDEMEM_DB = HERMES_HOME / "claudemem.db"
LOG_DIR = HERMES_HOME / "logs"


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] memory-reflector: {msg}"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "memory_reflector.log", "a") as f:
        f.write(line + "\n")
    print(line, file=sys.stderr)


def get_recent_conversations(since_hours: int = 6) -> list[dict]:
    """Extract recent conversation summaries from ClaudeMem DB."""
    conversations = []
    try:
        if not CLAUDEMEM_DB.exists():
            return conversations

        conn = sqlite3.connect(str(CLAUDEMEM_DB), timeout=5)
        conn.row_factory = sqlite3.Row

        # Get recent observations that look like conversation summaries
        cutoff = (datetime.now() - timedelta(hours=since_hours)).timestamp()
        rows = conn.execute(
            """SELECT content, importance, timestamp, category
               FROM observations
               WHERE timestamp > ? AND compressed = 0
               ORDER BY importance DESC, timestamp DESC
               LIMIT 20""",
            (cutoff,),
        ).fetchall()
        conn.close()

        for row in rows:
            conversations.append({
                "content": row["content"],
                "importance": row["importance"],
                "timestamp": row["timestamp"],
                "category": row["category"],
            })
    except Exception as e:
        log(f"Error reading conversations: {e}")

    return conversations


def generate_reflection(conversations: list[dict]) -> list[dict]:
    """Generate reflection observations from recent conversations."""
    observations = []

    if not conversations:
        return observations

    # Pattern 1: Extract user preferences
    prefs = []
    topics = []
    decisions = []
    issues_resolved = []

    for conv in conversations:
        content = conv.get("content", "").lower()

        # Detect preferences
        if any(w in content for w in ["i prefer", "i like", "i want", "i need", "my favorite", "always", "never"]):
            prefs.append(conv["content"])

        # Detect topics of interest
        if any(w in content for w in ["career", "job", "interview", "resume", "application"]):
            topics.append("career-ops")
        if any(w in content for w in ["server", "docker", "container", "service", "deploy"]):
            topics.append("infrastructure")
        if any(w in content for w in ["code", "programming", "develop", "script", "python"]):
            topics.append("development")
        if any(w in content for w in ["research", "learn", "study", "read", "book"]):
            topics.append("research")

        # Detect decisions
        if any(w in content for w in ["decided", "will use", "going to", "plan to", "chose"]):
            decisions.append(conv["content"])

        # Detect resolved issues
        if any(w in content for w in ["fixed", "resolved", "solved", "working now", "completed"]):
            issues_resolved.append(conv["content"])

    # Generate observations from patterns
    if prefs:
        # Save most important preference
        observations.append({
            "content": f"User preference observed: {prefs[0][:200]}",
            "importance": 0.8,
            "category": "preference",
            "source": "memory_reflector",
        })

    # Topic frequency
    from collections import Counter
    topic_counts = Counter(topics)
    for topic, count in topic_counts.most_common(3):
        if count >= 2:
            observations.append({
                "content": f"Frequent topic ({count}x recently): {topic}",
                "importance": 0.6,
                "category": "topic-interest",
                "source": "memory_reflector",
            })

    if decisions:
        observations.append({
            "content": f"Decision made: {decisions[0][:200]}",
            "importance": 0.75,
            "category": "decision",
            "source": "memory_reflector",
        })

    if issues_resolved:
        observations.append({
            "content": f"Issue resolved: {issues_resolved[0][:200]}",
            "importance": 0.7,
            "category": "sop",
            "source": "memory_reflector",
        })

    return observations


def save_observations(observations: list[dict]) -> int:
    """Save observations to ClaudeMem database."""
    saved = 0
    try:
        if not CLAUDEMEM_DB.exists():
            return 0

        conn = sqlite3.connect(str(CLAUDEMEM_DB), timeout=5)
        for obs in observations:
            try:
                conn.execute(
                    """INSERT INTO observations (content, importance, category, source, timestamp, compressed)
                       VALUES (?, ?, ?, ?, ?, 0)""",
                    (
                        obs["content"],
                        obs["importance"],
                        obs.get("category", "context"),
                        obs.get("source", "memory_reflector"),
                        datetime.now().timestamp(),
                    ),
                )
                saved += 1
            except Exception:
                continue
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"Error saving observations: {e}")

    return saved


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Self-Evolving Memory Reflector")
    parser.add_argument("--since", default="6", type=str, help="Hours to look back")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    since_hours = int(args.since)
    log(f"Starting reflection (last {since_hours}h)")

    # Get recent conversations
    conversations = get_recent_conversations(since_hours)
    log(f"Found {len(conversations)} recent conversation(s)")

    # Generate reflections
    observations = generate_reflection(conversations)
    log(f"Generated {len(observations)} observation(s)")

    # Save to ClaudeMem
    saved = save_observations(observations)
    log(f"Saved {saved} observation(s) to ClaudeMem")

    if args.json:
        print(json.dumps({
            "status": "completed",
            "conversations_analyzed": len(conversations),
            "observations_generated": len(observations),
            "observations_saved": saved,
        }, indent=2))
    else:
        print(f"Memory reflector: {saved} observation(s) saved from {len(conversations)} conversation(s)")


if __name__ == "__main__":
    main()
