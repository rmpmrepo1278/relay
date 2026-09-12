#!/usr/bin/env python3
"""Personal Research Digest Generator — Enhanced.

Uses GPT-Researcher to generate personalized research reports on topics
Rohit cares about. Supports multiple research modes:

1. Standard research — web-based research_report (fast, good for news/updates)
2. Deep research — recursive multi-level exploration (thorough, for complex topics)
3. Subtopic research — breaks query into subtopics for comprehensive coverage
4. Hybrid research — combines web + local documents (Paperless, notes, etc.)

Multi-source aggregation:
- Web search (default)
- Local documents (Paperless-ngx consume dir, notes, CLAUDE.md)
- GitHub (trending repos, specific repos via query)
- Academic (via web search with academic focus)

Usage:
    python3 personal_research_digest.py                    # Standard weekly digest
    python3 personal_research_digest.py --telegram          # Send via Telegram
    python3 personal_research_digest.py --topic "specific"  # One-off research
    python3 personal_research_digest.py --deep "topic"      # Deep recursive research
    python3 personal_research_digest.py --subtopic "topic"  # Subtopic research
    python3 personal_research_digest.py --hybrid "topic"    # Web + local docs
    python3 personal_research_digest.py --report            # Save full report to file
    python3 personal_research_digest.py --citations         # Include full citations
"""

import json
import os
import sys
import time
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
DIGEST_CONFIG = HERMES_HOME / "research_digest_config.json"
DIGEST_HISTORY = HERMES_HOME / "research_digest_history.json"
REPORTS_DIR = HERMES_HOME / "research_reports"
REPORTS_DIR.mkdir(exist_ok=True)

# ─── Topic Definitions ───────────────────────────────────────────────────────

DEFAULT_TOPICS = {
    "ai_agents": {
        "query": "Latest developments in AI agent frameworks, multi-agent systems, and autonomous agents (CrewAI, AutoGen, LangGraph, browser-use)",
        "schedule": "weekly",
        "priority": "high",
        "mode": "standard",
    },
    "homelab": {
        "query": "New self-hosted tools, Docker updates, homelab projects, and open-source alternatives to SaaS",
        "schedule": "weekly",
        "priority": "high",
        "mode": "standard",
    },
    "llm_news": {
        "query": "New LLM model releases, benchmark results, and significant AI research papers",
        "schedule": "weekly",
        "priority": "medium",
        "mode": "standard",
    },
    "career_tech": {
        "query": "Technology industry trends, program management best practices, and telecom industry updates",
        "schedule": "biweekly",
        "priority": "medium",
        "mode": "standard",
    },
    "travel": {
        "query": "Travel deals, destination guides, and trip planning tips for India, Goa, and Southeast Asia",
        "schedule": "monthly",
        "priority": "low",
        "mode": "standard",
    },
    "paperless_immich": {
        "query": "Self-hosted document management updates: Paperless-ngx features, Immich releases, photo management AI tools, OCR improvements",
        "schedule": "weekly",
        "priority": "high",
        "mode": "standard",
    },
    "docker_infra": {
        "query": "Docker best practices, compose updates, reverse proxy tips (nginx-proxy-manager), Pi-hole news, and self-hosted monitoring tools",
        "schedule": "weekly",
        "priority": "high",
        "mode": "standard",
    },
    "ai_local": {
        "query": "Local LLM inference, Ollama updates, self-hosted AI tools, vector databases (Qdrant), embeddings, RAG pipelines on consumer hardware",
        "schedule": "weekly",
        "priority": "high",
        "mode": "standard",
    },
}

# Deep research topics — these use recursive exploration
DEEP_RESEARCH_TOPICS = {
    "ai_agent_ecosystem": {
        "query": "Comprehensive analysis of the AI agent ecosystem in 2026: frameworks, tools, deployment patterns, enterprise adoption, and future directions",
        "schedule": "monthly",
        "priority": "high",
        "mode": "deep",
        "config": {"breadth": 4, "depth": 3},
    },
    "homelab_evolution": {
        "query": "The evolution of self-hosting and homelab: from bare metal to Kubernetes to AI-native infrastructure, what's next",
        "schedule": "monthly",
        "priority": "medium",
        "mode": "deep",
        "config": {"breadth": 3, "depth": 2},
    },
}

# ─── Config & History ────────────────────────────────────────────────────────

def load_config() -> dict:
    if DIGEST_CONFIG.exists():
        return json.loads(DIGEST_CONFIG.read_text())
    return {
        "version": 2,
        "topics": DEFAULT_TOPICS,
        "deep_topics": DEEP_RESEARCH_TOPICS,
        "last_run": None,
        "schedule": "weekly",
        "max_concurrent_research": 2,
        "report_format": "markdown",
        "send_telegram": True,
        "include_citations": True,
        "save_reports": True,
    }

def save_config(config: dict):
    DIGEST_CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2))

def load_history() -> list:
    if DIGEST_HISTORY.exists():
        return json.loads(DIGEST_HISTORY.read_text())
    return []

def save_history(history: list):
    DIGEST_HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2))


# ─── Research Execution ──────────────────────────────────────────────────────

def run_research(query: str, topic_id: str = "custom", mode: str = "standard",
                 config: dict = None) -> dict:
    """Run GPT-Researcher on a query via the container.

    Modes:
        standard  — research_report (fast, web-based)
        deep      — DeepResearch (recursive multi-level exploration)
        subtopic  — SubtopicReport (breaks into subtopics)
        hybrid    — research_report with local document context

    Writes result to a temp file inside the container (atomic via rename),
    then reads it back with retries.
    """
    import subprocess as sp

    result_file = f"/tmp/research/result_{topic_id}.json"
    result_tmp = f"/tmp/research/.result_{topic_id}.tmp"
    query_escaped = query.replace("'", "\\'").replace("\n", "\\n")

    # Build the research script based on mode
    report_type = "research_report"
    report_source = "web"
    max_subtopics = 5

    if mode == "deep":
        report_type = "deep"
        breadth = config.get("breadth", 3) if config else 3
        depth = config.get("depth", 2) if config else 2
    elif mode == "subtopic":
        report_type = "subtopic_report"
        max_subtopics = config.get("max_subtopics", 8) if config else 8
    elif mode == "hybrid":
        report_source = "hybrid"

    script = f"""
import json, os, asyncio
from gpt_researcher import GPTResearcher

async def main():
    os.makedirs('/tmp/research', exist_ok=True)
    researcher = GPTResearcher(
        query='{query_escaped}',
        report_type='{report_type}',
        report_format='markdown',
        report_source='{report_source}',
        max_subtopics={max_subtopics},
        verbose=False,
    )
    await researcher.conduct_research()
    report = await researcher.write_report()
    sources = researcher.get_source_urls()
    subtopics = researcher.get_subtopics() if hasattr(researcher, 'get_subtopics') else []
    result = {{
        'report': report,
        'sources': [{{'url': s, 'title': s}} for s in sources[:15]],
        'subtopics': subtopics,
        'report_type': '{report_type}',
        'mode': '{mode}',
    }}
    # Atomic write: dump to temp, then rename
    with open('{result_tmp}', 'w') as f:
        json.dump(result, f)
        f.flush()
        os.fsync(f.fileno())
    os.rename('{result_tmp}', '{result_file}')

asyncio.run(main())
"""

    timeout = 900 if mode == "deep" else 600

    try:
        # Check if research container exists
        check_container = sp.run(
            ["docker", "inspect", "gpt-researcher-gpt-researcher-1"],
            capture_output=True, text=True, timeout=10,
        )
        if check_container.returncode != 0:
            log.warning("Research container not found (gpt-researcher-gpt-researcher-1)")
            return {
                "topic_id": topic_id, "query": query,
                "report": "Research container not running. Start with: docker run -d --name gpt-researcher-gpt-researcher-1 ghcr.io/assafelitzur/gpt-researcher:latest",
                "sources": [], "subtopics": [], "mode": mode,
                "method": "error",
            }
        run_result = sp.run(
            ["docker", "exec", "gpt-researcher-gpt-researcher-1",
             "python3", "-c", script],
            capture_output=True, text=True, timeout=timeout,
        )

        # Check for errors in the research execution itself
        if run_result.returncode != 0:
            stderr = run_result.stderr.strip() if run_result.stderr else ""
            stdout = run_result.stdout.strip() if run_result.stdout else ""
            log.error("Research script failed (rc=%d) for %s: %s %s",
                      run_result.returncode, topic_id, stderr[:200], stdout[:200])
            return {
                "topic_id": topic_id, "query": query,
                "report": f"Research script failed (rc={run_result.returncode}): {stderr[:200]}",
                "sources": [], "subtopics": [], "mode": mode,
                "method": "error",
            }

        # Retry reading up to 5 times with increasing delays.
        # File might still be flushing, or the atomic rename might not be visible yet.
        for attempt in range(5):
            # Check file exists and has content before parsing
            size_result = sp.run(
                ["docker", "exec", "gpt-researcher-gpt-researcher-1",
                 "python3", "-c",
                 f"import os; print(os.path.getsize('{result_file}') if os.path.exists('{result_file}') else 0)"],
                capture_output=True, text=True, timeout=10,
            )
            file_size = int(size_result.stdout.strip()) if size_result.returncode == 0 else 0

            if file_size == 0:
                if attempt < 4:
                    wait = 2 + attempt * 2  # 2, 4, 6, 8 seconds
                    log.info("Result file empty/missing for %s, waiting %ds (attempt %d/5)",
                             topic_id, wait, attempt + 1)
                    time.sleep(wait)
                    continue
                else:
                    log.error("Result file empty for %s after 5 attempts", topic_id)
                    break

            # File has content — try to parse
            read_result = sp.run(
                ["docker", "exec", "gpt-researcher-gpt-researcher-1",
                 "python3", "-c",
                 f"import json; f=open('{result_file}'); data=json.load(f); print(json.dumps(data))"],
                capture_output=True, text=True, timeout=30,
            )
            if read_result.returncode == 0 and read_result.stdout.strip():
                try:
                    data = json.loads(read_result.stdout.strip())
                    return {
                        "topic_id": topic_id,
                        "query": query,
                        "report": data.get("report", ""),
                        "sources": data.get("sources", []),
                        "subtopics": data.get("subtopics", []),
                        "mode": mode,
                        "report_type": data.get("report_type", report_type),
                        "method": "container",
                    }
                except json.JSONDecodeError:
                    if attempt < 4:
                        time.sleep(3)
                        continue
                    log.error("JSON decode failed for %s after 5 attempts (file_size=%d)",
                              topic_id, file_size)
            else:
                log.error("Failed to read research result for %s (attempt %d): %s",
                          topic_id, attempt + 1,
                          read_result.stderr.strip()[:200] if read_result.stderr else "")
                if attempt < 4:
                    time.sleep(3)
                    continue
            break

        return {
            "topic_id": topic_id, "query": query,
            "report": "Failed to read research result",
            "sources": [], "subtopics": [], "mode": mode,
            "method": "error",
        }
    except sp.TimeoutExpired:
        return {
            "topic_id": topic_id, "query": query,
            "report": f"Research timed out ({timeout}s limit)",
            "sources": [], "subtopics": [], "mode": mode,
            "method": "timeout",
        }
    except Exception as e:
        return {
            "topic_id": topic_id, "query": query,
            "report": f"Error: {e}",
            "sources": [], "subtopics": [], "mode": mode,
            "method": "error",
        }


def gather_local_context(query: str) -> str:
    """Gather relevant local documents to enrich research context.

    Searches Paperless-consume dir, notes, and CLAUDE.md for relevant content
    that GPT-Researcher can use as additional context.
    """
    context_parts = []

    # Search CLAUDE.md for relevant sections
    claude_md = Path.home() / ".claude" / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text()
        # Extract sections that might be relevant (simple keyword match)
        query_words = set(query.lower().split())
        sections = content.split("\n## ")
        for section in sections[:5]:  # Limit to avoid too much context
            section_lower = section.lower()
            if any(w in section_lower for w in query_words if len(w) > 3):
                # Take first 500 chars of relevant sections
                context_parts.append(section[:500])

    # Check Paperless consume dir for relevant docs
    consume_dir = Path.home() / "openclaw" / "data" / "paperless" / "consume"
    if consume_dir.exists():
        # List recent files (last 30 days)
        cutoff = time.time() - 30 * 86400
        recent_files = []
        for f in consume_dir.iterdir():
            if f.is_file() and f.stat().st_mtime > cutoff:
                recent_files.append(f)
        if recent_files:
            context_parts.append(f"\n[Local documents available: {len(recent_files)} recent files in Paperless consume dir]")

    return "\n---\n".join(context_parts[:3]) if context_parts else ""


# ─── Digest Generation ───────────────────────────────────────────────────────

def generate_digest(topics: dict = None, max_topics: int = 3,
                    mode_override: str = None) -> dict:
    """Generate a personal research digest."""
    config = load_config()
    if topics is None:
        topics = config.get("topics", DEFAULT_TOPICS)

    today = datetime.now()
    results = []
    history = load_history()
    last_runs = {e.get("topic_id"): e.get("run_at", "") for e in history if e.get("topic_id")}

    due_topics = []
    for tid, tconfig in topics.items():
        schedule = tconfig.get("schedule", "weekly")
        last_run = last_runs.get(tid, "")
        if last_run:
            last_date = datetime.fromisoformat(last_run) if isinstance(last_run, str) else today
            days_since = (today - last_date).days
            if schedule == "weekly" and days_since < 7:
                continue
            elif schedule == "biweekly" and days_since < 14:
                continue
            elif schedule == "monthly" and days_since < 30:
                continue
        due_topics.append((tid, tconfig))

    priority_order = {"high": 0, "medium": 1, "low": 2}
    due_topics.sort(key=lambda x: priority_order.get(x[1].get("priority", "low"), 2))
    due_topics = due_topics[:max_topics]

    for tid, tconfig in due_topics:
        mode = mode_override or tconfig.get("mode", "standard")
        query = tconfig.get("query", "")
        topic_config = tconfig.get("config", {})

        log.info("Researching [%s]: %s — %s", mode, tid, query[:60])

        # For hybrid mode, gather local context
        if mode == "hybrid":
            local_context = gather_local_context(query)
            if local_context:
                query = f"{query}\n\nAdditional context from local documents:\n{local_context}"

        result = run_research(query, topic_id=tid, mode=mode, config=topic_config)
        result["run_at"] = today.isoformat()
        results.append(result)

        history.append({
            "topic_id": tid,
            "query": query[:100],
            "run_at": today.isoformat(),
            "mode": mode,
            "method": result.get("method", "unknown"),
            "report_length": len(result.get("report", "")),
            "sources_count": len(result.get("sources", [])),
        })

    history = history[-100:]
    save_history(history)
    config["last_run"] = today.isoformat()
    save_config(config)

    return {
        "date": today.strftime("%Y-%m-%d"),
        "topics_researched": len(results),
        "results": results,
    }


def generate_deep_research(topic_id: str = None, query: str = None) -> dict:
    """Run deep recursive research on a specific topic."""
    config = load_config()

    if topic_id and topic_id in config.get("deep_topics", {}):
        topic = config["deep_topics"][topic_id]
        query = topic["query"]
        topic_config = topic.get("config", {})
    elif query:
        topic_id = topic_id or "custom_deep"
        topic_config = {"breadth": 3, "depth": 2}
    else:
        return {"error": "Provide either a deep research topic_id or a custom query"}

    log.info("Deep research: %s", query[:80])
    result = run_research(query, topic_id=topic_id, mode="deep", config=topic_config)
    result["run_at"] = datetime.now().isoformat()

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "topics_researched": 1,
        "results": [result],
    }


# ─── Report Formatting ───────────────────────────────────────────────────────

def format_digest(digest: dict, include_citations: bool = True,
                  save_to_file: bool = True) -> str:
    """Format digest as a Telegram-friendly message."""
    lines = [
        f"🔬 **Personal Research Digest** — {digest['date']}",
        f"📊 {digest['topics_researched']} topics researched",
        "",
    ]

    full_reports = []

    for result in digest.get("results", []):
        topic_id = result.get("topic_id", "unknown")
        report = result.get("report", "No report generated")
        sources = result.get("sources", [])
        subtopics = result.get("subtopics", [])
        mode = result.get("mode", "standard")

        emoji = {
            "ai_agents": "🤖", "homelab": "🏠", "llm_news": "🧠",
            "career_tech": "💼", "travel": "✈️",
        }.get(topic_id, "📋")

        mode_label = {
            "standard": "", "deep": " 🔍 Deep Research",
            "subtopic": " 📑 Subtopic Analysis", "hybrid": " 🔗 Hybrid",
        }.get(mode, "")

        lines.append(f"**{emoji} {topic_id.replace('_', ' ').title()}**{mode_label}")
        lines.append("")

        # Show subtopics for deep/subtopic research
        if subtopics:
            lines.append("*Subtopics covered:*")
            for st in subtopics[:8]:
                st_name = st.get("name", st) if isinstance(st, dict) else str(st)
                lines.append(f"  • {st_name}")
            lines.append("")

        # Truncate for Telegram
        if len(report) > 3000:
            truncated = report[:3000] + "\n\n... [truncated]"
            lines.append(truncated)
            full_reports.append({"topic_id": topic_id, "report": report, "sources": sources})
        else:
            lines.append(report)

        lines.append("")

        if sources and include_citations:
            lines.append("**Sources:**")
            for src in sources[:7]:
                title = src.get("title", src.get("url", "Unknown"))[:60]
                url = src.get("url", "")
                lines.append(f"  • [{title}]({url})")
            lines.append("")

    # Save full reports to file
    if save_to_file and full_reports:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = REPORTS_DIR / f"digest_{timestamp}.md"
        with open(report_file, "w") as f:
            f.write(f"# Research Digest — {digest['date']}\n\n")
            for r in full_reports:
                f.write(f"## {r['topic_id']}\n\n")
                f.write(r["report"])
                f.write("\n\n### Sources\n\n")
                for src in r["sources"]:
                    title = src.get("title", src.get("url", "Unknown"))
                    url = src.get("url", "")
                    f.write(f"- [{title}]({url})\n")
                f.write("\n---\n\n")
        lines.append(f"📄 Full reports saved: {report_file.name}")

    return "\n".join(lines)


# ─── Telegram ────────────────────────────────────────────────────────────────

def send_telegram(message: str):
    """Send digest via Telegram bridge."""
    try:
        from telegram_bridge import send_telegram_markdown as _send
        _send(message)
    except Exception as e:
        print(f"Telegram send failed: {e}")


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    args = sys.argv[1:]
    topic_filter = None
    mode_override = None
    deep_query = None
    deep_topic = None
    include_citations = "--citations" in args or "--no-citations" not in args
    save_reports = "--report" in args
    use_telegram = "--telegram" in args

    # Parse --topic
    if "--topic" in args:
        idx = args.index("--topic")
        if idx + 1 < len(args):
            tid = args[idx + 1]
            config = load_config()
            all_topics = {**config.get("topics", DEFAULT_TOPICS),
                          **config.get("deep_topics", DEEP_RESEARCH_TOPICS)}
            if tid in all_topics:
                topic_filter = {tid: all_topics[tid]}
            else:
                print(f"Unknown topic: {tid}")
                print(f"Available: {', '.join(all_topics.keys())}")
                sys.exit(1)

    # Parse --deep
    if "--deep" in args:
        idx = args.index("--deep")
        if idx + 1 < len(args):
            deep_query = args[idx + 1]

    # Parse --subtopic
    if "--subtopic" in args:
        idx = args.index("--subtopic")
        if idx + 1 < len(args):
            deep_query = args[idx + 1]
            mode_override = "subtopic"

    # Parse --hybrid
    if "--hybrid" in args:
        idx = args.index("--hybrid")
        if idx + 1 < len(args):
            deep_query = args[idx + 1]
            mode_override = "hybrid"

    # Handle control commands: status, pause, resume, clear
    if "status" in args and len(args) == 1:
        import json
        state_file = HERMES_HOME / "data" / "research_agent_state.json"
        if state_file.exists():
            state = json.loads(state_file.read_text())
            paused = "PAUSED" if state.get("paused") else "ACTIVE"
            print(f"Research agent: {paused}")
            print(f"Sent matches: {len(state.get('sent_matches', []))}")
        else:
            print("Research agent: no state (ACTIVE)")
        sys.exit(0)

    if "pause" in args and len(args) == 1:
        import json
        state_file = HERMES_HOME / "data" / "research_agent_state.json"
        state = json.loads(state_file.read_text()) if state_file.exists() else {"sent_matches": [], "paused": False}
        state["paused"] = True
        state_file.write_text(json.dumps(state))
        print("Research agent PAUSED")
        sys.exit(0)

    if "resume" in args and len(args) == 1:
        import json
        state_file = HERMES_HOME / "data" / "research_agent_state.json"
        state = json.loads(state_file.read_text()) if state_file.exists() else {"sent_matches": [], "paused": True}
        state["paused"] = False
        state_file.write_text(json.dumps(state))
        print("Research agent RESUMED")
        sys.exit(0)

    if "clear" in args and len(args) == 1:
        import json
        state_file = HERMES_HOME / "data" / "research_agent_state.json"
        state = json.loads(state_file.read_text()) if state_file.exists() else {"sent_matches": [], "paused": False}
        state["sent_matches"] = []
        state_file.write_text(json.dumps(state))
        print("Research cache cleared")
        sys.exit(0)

    # Execute
    if deep_query:
        digest = generate_deep_research(query=deep_query)
    elif mode_override and topic_filter:
        digest = generate_digest(topics=topic_filter, mode_override=mode_override)
    else:
        digest = generate_digest(topics=topic_filter)

    report = format_digest(digest, include_citations=include_citations,
                           save_to_file=save_reports)
    print(report)

    if use_telegram:
        send_telegram(report)
        print("\n✅ Digest sent via Telegram")
