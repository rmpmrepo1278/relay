#!/usr/bin/env python3
"""
mind_loop.py — The Autonomous Mind Loop for Hermes.

This is the central intelligence that gives Hermes a "mind of its own."
It's not just a responder — it's a continuously thinking, observing, planning
and acting agent that connects all the other intelligence modules.

Architecture:
    OBSERVE → CONNECT → ANTICIPATE → PLAN → ACT → REFLECT → EVOLVE

Each cycle:
    1. OBSERVE: Gather signals from all sources (health, email, calendar,
       HN, arXiv, GitHub, job market, Telegram history, Claude sessions)
    2. CONNECT: Find cross-domain patterns and novel insights
    3. ANTICIPATE: Predict what Rohit will need before he asks
    4. PLAN: Create multi-step action plans
    5. ACT: Execute via task_queue, proactive modules, direct tool use
    6. REFLECT: Did the action help? What did we learn?
    7. EVOLVE: Update goals, strategies, personal model

Runs as a daemon process, one cycle every 30 minutes.
State persists in ~/.hermes/state/mind_loop.json

Usage:
    python3 mind_loop.py              # Run one cycle
    python3 mind_loop.py --daemon     # Run continuously (30min intervals)
    python3 mind_loop.py --status     # Show current mind state
    python3 mind_loop.py --insight    # Force cross-domain insight generation
"""

from __future__ import annotations
import json
import os
import subprocess
import sys
import time
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Import the new intelligence modules (HERMES_HOME defined below)
_NEW_MODULES = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERMES_HOME = Path.home() / ".hermes"
STATE_DIR = HERMES_HOME / "state"
STATE_FILE = STATE_DIR / "mind_loop.json"
LOG_FILE = HERMES_HOME / "logs" / "mind_loop.log"
INBOX_FILE = HERMES_HOME / "data" / "mind_insights.jsonl"

STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# Import new intelligence modules now that HERMES_HOME is defined
try:
    sys.path.insert(0, str(HERMES_HOME / "scripts"))
    import insight_engine
    import personal_model
    import narrative_memory
    import feedback_loop
    _NEW_MODULES = True
except ImportError:
    _NEW_MODULES = False

import mind_loop_integration
# Import new infrastructure modules
try:
    from hermes_tracing import Tracer
    _tracer = Tracer("mind_loop")
except Exception:
    _tracer = None

if _tracer is None:
    from contextlib import nullcontext

    class _NullSpan:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def set_attribute(self, *a, **kw): pass

    class _NullTracer:
        def span(self, _name, **kw): return _NullSpan()

    _tracer = _NullTracer()

try:
    from guardrails import Guardrails, Policy
    _guardrails = Guardrails()
    # Register domain policies
    for domain in ("INFRA", "CAREER", "KNOWLEDGE", "PERSONAL", "MEDIA"):
        _guardrails.add_policy(Policy.defaults(domain))
except Exception:
    _guardrails = None

ACTION_DOMAINS = {
    "send_telegram": "PERSONAL",
    "add_task": "PERSONAL",
    "run_command": "INFRA",
}

try:
    from quality_tracker import QualityTracker
    _quality_tracker = QualityTracker()
except Exception:
    _quality_tracker = None

try:
    from hermes_memory import HermesMemory
    _memory = HermesMemory()
except Exception:
    _memory = None

try:
    from graphrag import GraphRAG
    _graphrag = GraphRAG()
except Exception:
    _graphrag = None

try:
    from gnap import GNAPAgent, Capability
    _gnap_agent = GNAPAgent("hermes-mind-loop")
    _gnap_agent.add_capability(Capability("health_check", "Check homelab health"))
    _gnap_agent.add_capability(Capability("pattern_detection", "Cross-domain pattern finding"))
    _gnap_agent.add_capability(Capability("proactive_messaging", "Send proactive insights"))
    _gnap_agent.register()
except Exception:
    _gnap_agent = None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {level} mind_loop: {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "version": 1,
        "created": datetime.now(timezone.utc).isoformat(),
        "last_cycle": None,
        "cycle_count": 0,
        "goals": [],
        "insights": [],
        "patterns": [],
        "personal_model": {
            "work_patterns": {},       # when is Rohit most active?
            "stress_indicators": [],   # what patterns precede stress?
            "decision_style": {},      # how does Rohit make decisions?
            "unspoken_needs": [],      # needs Rohit hasn't articulated
        },
        "signal_history": [],         # last N signals observed
        "action_history": [],         # last N actions taken
        "reflection_log": [],         # what we've learned
        "external_signals": {
            "hn_trending": [],
            "arxiv_new": [],
            "github_trending": [],
            "job_market": [],
        },
    }


def save_state(state: dict):
    state["last_cycle"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def append_insight(insight: dict):
    """Append an insight to the persistent insight log."""
    with open(INBOX_FILE, "a") as f:
        f.write(json.dumps(insight, default=str) + "\n")


# ---------------------------------------------------------------------------
# OBSERVE: Gather signals from all sources
# ---------------------------------------------------------------------------
def observe_health() -> dict:
    """Health snapshot with a live fallback when signals are stale/missing.

    The producer is `healthcheck.sh` (it writes data/health_signals.json). If
    the file is missing or older than 15 minutes, regenerate it here so the
    mind loop is self-sufficient and never reports "Health score: ?".
    """
    try:
        sf = HERMES_HOME / "data" / "health_signals.json"
        if sf.exists():
            age_s = time.time() - sf.stat().st_mtime
            if age_s <= 15 * 60:
                return json.loads(sf.read_text())
        log("health_signals.json missing/stale — regenerating via healthcheck.sh")
        subprocess.run(
            ["bash", str(HERMES_HOME / "scripts" / "healthcheck.sh")],
            capture_output=True,
            timeout=90,
        )
        if sf.exists():
            return json.loads(sf.read_text())
    except Exception:
        pass
    return {}


def observe_email() -> dict:
    """Check for new emails. The full digest is generated once per day by the
    scheduler (email_intelligence job, 12:00). This loop only surfaces a digest
    if one was pushed today — it never re-runs the generator, which is what
    caused duplicate email messages every 30s cycle."""
    digest_file = HERMES_HOME / "data" / "alerts_inbox.jsonl"
    if digest_file.exists():
        try:
            content = digest_file.read_text()
            if "email" in content.lower() or "digest" in content.lower():
                return {"has_actionable": "actionable" in content.lower()}
        except Exception:
            pass
    return {}


def observe_calendar() -> dict:
    """Check upcoming calendar events."""
    try:
        result = subprocess.run(
            ["python3", str(HERMES_HOME / "scripts/proactive/calendar_manager.py"), "--upcoming"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return {"upcoming": result.stdout.strip()}
    except Exception:
        pass
    return {}


def observe_external_signals() -> dict:
    """Monitor external signals: HN, arXiv, GitHub trending, job market."""
    signals = {}

    # Hn-buzz: trending topics
    try:
        result = subprocess.run(
            ["python3", "-c", """
import urllib.request, json
req = urllib.request.Request("https://hacker-news.firebaseio.com/v0/topstories.json")
with urllib.request.urlopen(req, timeout=10) as r:
    ids = json.loads(r.read())[:10]
for i in ids[:5]:
    req2 = urllib.request.Request(f"https://hacker-news.firebaseio.com/v0/item/{i}.json")
    with urllib.request.urlopen(req2, timeout=10) as r2:
        s = json.loads(r2.read())
        title = s.get('title','')[:80].replace('|','/')
        score = s.get('score', 0)
        url = s.get('url', f'https://news.ycombinator.com/item?id={i}')
        print(f"{score}|{i}|{title}|{url}")
"""],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            signals["hn_trending"] = []
            for line in result.stdout.strip().split("\n"):
                parts = line.split("|", 3)
                if len(parts) == 4:
                    signals["hn_trending"].append({
                        "score": int(parts[0]),
                        "id": parts[1],
                        "title": parts[2],
                        "url": parts[3],
                    })
    except Exception:
        pass

    return signals


def observe_telegram_history() -> dict:
    """Read recent Telegram conversation for context + extract commitments."""
    log_file = HERMES_HOME / "logs" / "agent.log"
    if not log_file.exists():
        return {}
    try:
        # Get last 50 lines of inbound messages
        result = subprocess.run(
            ["grep", "inbound message", str(log_file)],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")[-20:]
            return {"recent_messages": lines}
    except Exception:
        pass
    return {}


def observe_commitments() -> dict:
    """Check commitment status — overdue, upcoming, health."""
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        from commitment_tracker import check_overdue, get_upcoming, get_status
        overdue = check_overdue()
        upcoming = get_upcoming(hours=2)
        status = get_status()
        return {
            "overdue": overdue,
            "upcoming": upcoming,
            "health": status["stats"],
            "has_overdue": len(overdue) > 0,
            "has_upcoming": len(upcoming) > 0,
        }
    except Exception:
        return {}


def run_observation() -> dict:
    """Run all observation modules."""
    log("Starting observation phase...")
    signals = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "health": observe_health(),
        "email": observe_email(),
        "calendar": observe_calendar(),
        "external": observe_external_signals(),
        "telegram": observe_telegram_history(),
        "commitments": observe_commitments(),
    }
    log(f"Observation complete. Health score: {signals['health'].get('score', '?')}")
    return signals


# ---------------------------------------------------------------------------
# CONNECT: Cross-domain pattern finding
# ---------------------------------------------------------------------------
def find_patterns(state: dict, signals: dict) -> list:
    """Find cross-domain patterns and novel insights."""
    insights = []

    # Pattern 1: Health degradation → productivity impact
    health = signals.get("health", {})
    checks = health.get("checks", {})
    failed = [n for n, c in checks.items() if c.get("status") not in ("ok", "healthy")]
    if failed:
        insights.append({
            "type": "health_alert",
            "severity": "high" if len(failed) > 2 else "medium",
            "content": f"System issues detected: {', '.join(failed)}. This may impact productivity.",
            "action_suggested": "investigate_and_fix",
        })

    # Pattern 2: Email urgency + calendar proximity
    email = signals.get("email", {})
    calendar = signals.get("calendar", {})
    if email.get("has_actionable") and calendar.get("upcoming"):
        insights.append({
            "type": "time_sensitive",
            "content": "Actionable emails + upcoming calendar events. May need to prioritize.",
            "action_suggested": "surface_to_telegram",
        })

    # Pattern 3: External signal relevance
    # ponytail: write HN findings to daily digest file instead of sending
    # directly to Telegram. The proactive_orchestrator picks them up once
    # per day and composes a single digest.
    external = signals.get("external", {})
    hn = external.get("hn_trending", [])
    interest_keywords = ["ai", "llm", "agent", "docker", "kubernetes", "rust", "self-host"]
    relevant = [s for s in hn if any(kw in s.get("title", "").lower() for kw in interest_keywords)]
    if relevant:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        digest_file = HERMES_HOME / "data" / f"daily_digest_{today}.md"
        # ponytail: skip if digest already written today — prevents re-sending HN on every 30-min cycle
        if digest_file.exists() and "trending HN" in digest_file.read_text():
            pass  # HN section already in today's digest
        else:
            existing = digest_file.read_text() if digest_file.exists() else ""
            # Build new HN block (single block, no trailing double-newline)
            new_hn_lines = [f"🔥 **{len(relevant)} trending HN post(s) match your interests:**"]
            for item in relevant[:5]:
                title = item.get("title", "?")
                url = item.get("url", f"https://news.ycombinator.com/item?id={item.get('id','')}")
                score = item.get("score", 0)
                new_hn_lines.append(f"• [{score}↑] {title}")
                new_hn_lines.append(f"  {url}")
            new_hn_block = "\n".join(new_hn_lines)
            # Replace existing HN block if present, otherwise append
            hn_header = "🔥 **"
            if hn_header in existing:
                idx = existing.index(hn_header)
                # HN block ends at the next double-newline (next section) or end of file
                after_block = existing[idx:]
                end_idx = after_block.find("\n\n")
                if end_idx != -1:
                    # Replace from header to the double-newline (keep what comes after)
                    existing = existing[:idx] + new_hn_block + existing[idx + end_idx:]
                else:
                    # No double-newline found — HN is the last section, replace to end
                    existing = existing[:idx] + new_hn_block
            else:
                if not existing:
                    existing = f"📡 **Daily Digest — {datetime.now().strftime('%b %d, %H:%M')}**"
                existing = existing.rstrip("\n") + "\n\n" + new_hn_block
            digest_file.write_text(existing.rstrip("\n") + "\n")

    # Pattern 4: Commitment health
    commitments = signals.get("commitments", {})
    if commitments.get("has_overdue"):
        overdue = commitments.get("overdue", [])
        insights.append({
            "type": "commitment_alert",
            "severity": "critical",
            "content": f"⚠️ {len(overdue)} overdue commitment(s)! Must fulfill immediately.",
            "action_suggested": "fulfill_commitment",
            "overdue": overdue,
        })
    elif commitments.get("has_upcoming"):
        upcoming = commitments.get("upcoming", [])
        insights.append({
            "type": "commitment_reminder",
            "severity": "medium",
            "content": f"📋 {len(upcoming)} commitment(s) due within 2 hours.",
            "action_suggested": "prepare_fulfillment",
            "upcoming": upcoming,
        })

    # Pattern 6: Feedback-driven priority adjustment (RL-lite)
    # Down-rank suggestion types user consistently ignores; up-rank engaged ones.
    try:
        import feedback_loop as _fb
        fb = _fb.load_feedback() if hasattr(_fb, 'load_feedback') else {}
        suggestions = fb.get("stats", {}).get("by_type", {}) if isinstance(fb, dict) else {}
        if suggestions:
            for stype, stats in suggestions.items():
                total = stats.get("total", 0)
                clicked = stats.get("clicked", 0)
                if total >= 3 and clicked == 0:
                    # User ignores these — reduce priority of any insight from this type
                    for ins in insights:
                        if ins.get("type", "").startswith(stype) and ins.get("priority", 5) > 3:
                            ins["priority"] = max(1, ins.get("priority", 5) - 2)
                            ins["reason"] = "downgraded via feedback_loop RL (ignore rate)"
                elif total >= 3 and clicked / total > 0.6:
                    # User engages — boost priority
                    for ins in insights:
                        if ins.get("type", "").startswith(stype):
                            ins["priority"] = min(10, ins.get("priority", 5) + 1)
                            ins["reason"] = "boosted via feedback_loop RL (engagement rate)"
    except Exception:
        pass
    # Pattern 5: Time-based patterns
    hour = datetime.now().hour
    if hour < 7:
        insights.append({
            "type": "time_pattern",
            "content": "Early morning — good time for autonomous work while Rohit sleeps.",
            "action_suggested": "run_maintenance_tasks",
        })
    elif 9 <= hour <= 11:
        insights.append({
            "type": "time_pattern",
            "content": "Morning peak hours — Rohit likely active. Good time for proactive updates.",
            "action_suggested": "send_morning_briefing",
        })

    log(f"Pattern finding: {len(insights)} insights generated")
    return insights


# ---------------------------------------------------------------------------
# ANTICIPATE: Predict what will be needed
# ---------------------------------------------------------------------------
def anticipate(state: dict, signals: dict, insights: list) -> list:
    """Generate anticipatory actions based on patterns and history."""
    anticipations = []

    # Anticipate: if backups are aging, schedule a check
    health = signals.get("health", {})
    backup_check = health.get("checks", {}).get("backups", {})
    if backup_check.get("status") == "warning":
        anticipations.append({
            "type": "preventive",
            "content": "Backups aging. Will verify Kopia snapshots.",
            "action": "verify_backups",
        })

    # Anticipate: if it's Friday afternoon, prepare weekly summary
    now = datetime.now()
    if now.weekday() == 4 and now.hour >= 14:  # Friday 2pm+
        anticipations.append({
            "type": "scheduled",
            "content": "Friday afternoon — time for weekly review.",
            "action": "prepare_weekly_review",
        })

    # Anticipate: if DuckDNS was recently fixed, verify it's stable
    dns_check = health.get("checks", {}).get("duckdns", {})
    if dns_check.get("status") != "ok":
        anticipations.append({
            "type": "monitoring",
            "content": "DuckDNS needs attention.",
            "action": "check_duckdns",
        })

    # --- Curiosity gap: notice things that have never been checked / domains unacted on ---
    try:
        import narrative_memory as _nm
        gap_actions = _nm.suggest_gap_actions()
        for ga in gap_actions[:2]:
            insights.append({
                "type": "curiosity_gap",
                "severity": "low",
                "content": ga["suggested_action"],
                "action_suggested": "investigate_and_fix",
                "source": "curiosity",
            })
    except Exception:
        pass

    log(f"Anticipation: {len(anticipations)} actions anticipated")

    # --- KG-aware anticipation: use semantic memory for proactive context ---
    try:
        import sys as _sys
        _kg_dir = Path.home() / ".hermes" / "knowledge_graph"
        _sys.path.insert(0, str(_kg_dir))
        from kg_engine import recent_sessions, search_nodes, get_all_types

        # Find recent sessions and extract active topics
        recents = recent_sessions(limit=5, since_hours=48)
        active_topics = set()
        for s in recents:
            # Session labels contain topic keywords
            label = s.get("label", "")
            for kw in ["Career", "AI", "Agent", "Docker", "Backup", "Career"]:
                if kw.lower() in label.lower():
                    active_topics.add(kw)

        # If Career is an active topic, anticipate career-relevant actions
        if "Career" in active_topics or "AI" in active_topics:
            stats = get_all_types()
            applied = []
            for edge_rel, count in stats["edge_relations"].items():
                if edge_rel in ("applied_to", "interested_in", "works_at"):
                    applied.append(edge_rel)
            if applied:
                anticipations.append({
                    "type": "contextual",
                    "content": "KG: Active topic 'Career' — check for new job postings and application follow-ups.",
                    "action": "check_career_pipeline",
                    "kg_context": {"active_topics": list(active_topics), "applied_edges": applied},
                })

        # Find people connected to companies of interest
        for company in ["Microsoft", "Amazon"]:
            company_node = None
            for n in search_nodes(company):
                if n.get("type") == "company":
                    company_node = n
                    break
            if company_node:
                # Check if there are any edges (connections) to this company
                edges = []
                from kg_engine import get_edges
                edges = get_edges(company_node["id"], direction="in")
                if edges:
                    anticipations.append({
                        "type": "contextual",
                        "content": f"KG: Connection found at {company} — review relationship context.",
                        "action": "review_company_connection",
                        "kg_context": {"company": company, "connection_count": len(edges)},
                    })
    except Exception as _kg_err:
        # Don't let KG errors break the anticipation loop
        pass

    return anticipations


# ---------------------------------------------------------------------------
# PLAN: Create action plans
# ---------------------------------------------------------------------------
def create_plan(insights: list, anticipations: list, state: dict | None = None) -> list:
    """
    Convert insights + anticipations + personal-model goals + narrative-memory
    gap-actions into concrete multi-step action plans.

    Enhancements over original:
      - Multi-step plans (sub-tasks chained with verify/repair)
      - Confidence gating via autonomous_self.get_confidence()
      - Goal-aligned planning (proposes actions for top life_goals)
      - Unacted-insight follow-up from narrative_memory
      - Quiet-hours filter
    """
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    is_quiet = now.hour < 7 or now.hour >= 23

    plans = []

    # --- 1. Insights → actions ---
    for insight in insights:
        sugg = insight.get("action_suggested", "")
        severity = insight.get("severity", "medium")
        priority = {"critical": 10, "high": 8, "medium": 5, "low": 3}.get(severity, 5)

        if sugg == "surface_to_telegram":
            plans.append({
                "action": "send_telegram",
                "content": insight["content"],
                "priority": priority,
                "source_insight": insight.get("content", "")[:80],
                "confidence": _check_confidence("send_telegram"),
            })
        elif sugg == "investigate_and_fix":
            plans.append({
                "action": "run_command",
                "command": _diagnose_from_insight(insight),
                "priority": priority,
                "source_insight": insight.get("content", "")[:80],
                "confidence": _check_confidence("run_command"),
                "verify": True,
            })
        elif sugg == "fulfill_commitment":
            plans.append({
                "action": "add_task",
                "content": f"FULFILL: {insight['content']}",
                "priority": 10,
                "source_insight": insight.get("content", "")[:80],
            })

    # --- 2. Anticipations → preventive actions ---
    for ant in anticipations:
        if ant.get("action", "") == "verify_backups":
            plans.append({
                "action": "run_command",
                "command": "sudo kopia snapshot list --json",
                "priority": 6,
                "confidence": _check_confidence("run_command"),
                "verify": True,
            })
        elif ant.get("action", "") == "send_morning_briefing":
            plans.append({
                "action": "send_telegram",
                "content": "morning_briefing",
                "priority": 7,
                "confidence": 0.9,
            })

    # --- 3. Goal-aligned planning (every cycle if goals available) ---
    if state and _NEW_MODULES:
        try:
            import personal_model as _pm
            goals = state.get("life_goals") or _pm.generate_life_goals()
            context = _pm.get_context_signals()

            for goal in goals[:3]:  # top 3 goals
                gap_actions = _pm.propose_goal_actions(goal, context)
                for ga in gap_actions:
                    plans.append({
                        "action": "add_task",
                        "content": f"GOAL[{goal['domain']}]: {ga}",
                        "priority": goal.get("priority", 5),
                        "goal_domain": goal.get("domain"),
                        "goal_title": goal.get("title"),
                        "confidence": _check_confidence("add_task"),
                    })
        except Exception as e:
            log(f"Goal-aligned planning error: {e}", level="WARN")

    # --- 4. Narrative memory gap follow-up (notices stale unacted insights) ---
    if _NEW_MODULES and not is_quiet:
        try:
            import narrative_memory as _nm
            gaps = _nm.suggest_gap_actions()
            for gap in gaps[:3]:
                plans.append({
                    "action": "add_task",
                    "content": gap["suggested_action"],
                    "priority": round(gap["confidence"] * 5) + 4,
                    "source": "narrative_gap",
                    "confidence": gap["confidence"],
                })
        except Exception as e:
            log(f"Narrative gap planning error: {e}", level="WARN")

     # --- 5. Authoring proposals (close insight→done loop via Telegram confirm) ---
    if state:
        for ins in insights:
            proposal = _propose_authoring_action(ins, state)
            if proposal:
                plans.append(proposal)

    # --- Quiet-hours filter (suppress non-critical outbound) ---
    if is_quiet:
        plans = [p for p in plans if (
            p.get("priority", 0) >= 9
            or p.get("action") in ("add_task", "run_command")
            or p.get("source") == "narrative_gap"
            or p.get("requires_confirm")
        )]

    # --- Deduplicate by content key ---
    seen = set()
    unique_plans = []
    for p in plans:
        key = json.dumps({**p}, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            unique_plans.append(p)

    # Cap total plans to prevent runaway
    if len(unique_plans) > 15:
        unique_plans = sorted(unique_plans, key=lambda p: p.get("priority", 0), reverse=True)[:15]

    log(f"Planning: {len(unique_plans)} unique actions planned "
        f"(insights={len(insights)}, anticipations={len(anticipations)})")
    return unique_plans


def _check_confidence(action: str) -> float:
    """Check calibrated confidence for an action type via autonomous_self."""
    try:
        import autonomous_self
        return autonomous_self.get_confidence(action)
    except Exception:
        return 0.6


def _diagnose_from_insight(insight: dict) -> str:
    """Turn an insight into a diagnostic command."""
    content = insight.get("content", "").lower()
    if "git" in content:
        return "git status --porcelain"
    if "disk" in content or "storage" in content:
        return "df -h / /mnt/usb"
    if "memory" in content or "ram" in content:
        return "free -h"
    if "backup" in content:
        return "kopia snapshot list --json | head -5"
    return "uptime && df -h"


def _verify_command(cmd: str) -> bool:
    """Return True if a command's output should be re-verified (placeholder)."""
    return False


# ---------------------------------------------------------------------------
# ACT: Execute plans
# ---------------------------------------------------------------------------
def execute_plan(plans: list, state: dict) -> list:
    """Execute the planned actions with guardrails, quality tracking, inline
    verification, and plan-repair on failure.

    Enhancements:
      - Plan-repair: failed run_command retried with a fallback command
      - Inline verification: post-action check + autonomous_self outcome recording
      - Narrative memory: every action recorded as an episode
      - Confidence-aware: low-confidence actions flagged for confirmation (stubbed)
    """
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        from decision_ledger import record as _ledger
    except ImportError:
        _ledger = None
    results = []

    for plan in plans:
        action = plan.get("action")
        try:
            # Guardrail check before execution
            if _guardrails:
                domain = ACTION_DOMAINS.get(action, "GENERAL")
                guard = _guardrails.check(domain, action, plan.get("content", ""))
                if not guard.allowed and not guard.required_confirmation:
                    results.append({"action": action, "status": "blocked", "reason": guard.reason})
                    log(f"Action blocked by guardrails: {action} — {guard.reason}", level="WARN")
                    continue

            # Confidence check — suppress low-confidence risky actions
            conf = plan.get("confidence", 0.6)
            if conf < 0.35 and action in ("run_command", "send_telegram") and plan.get("priority", 0) < 8:
                results.append({"action": action, "status": "deferred",
                                "reason": f"low confidence ({conf})", "confidence": conf})
                log(f"Deferring low-confidence action: {action} (conf={conf})")
                continue

            if action == "send_telegram":
                content = plan.get("content", "")
                if content == "morning_briefing":
                    content = compose_morning_briefing(state)
                if content:
                    send_to_telegram(content)
                    results.append({"action": "send_telegram", "status": "sent", "content_len": len(content)})
                    if _ledger:
                        try:
                            _ledger(
                                actor="mind_loop",
                                action="send_telegram",
                                rationale=plan.get("reason", "mind_loop plan action"),
                                predicted_outcome="informational",
                                target="",
                                params={"content_len": len(content)},
                                triggered_by="mind_cycle",
                            )
                        except Exception:
                            pass
                    _record_feedback("proactive_message", content[:100])
                    _record_narrative("action", content[:200], {
                        "source": plan.get("source_insight", ""),
                        "domain": "personal",
                        "outcome": "sent",
                    })
                    if _quality_tracker:
                        _quality_tracker.record_action(domain="PERSONAL", proactive=True, outcome="sent")

            elif action == "add_task":
                task_queue_add(plan.get("content", ""), priority=plan.get("priority", 5))
                results.append({"action": "add_task", "status": "added"})
                _record_narrative("action", plan.get("content", ""), {
                    "domain": plan.get("goal_domain", "task"),
                    "outcome": "added",
                })

            elif action == "run_command":
                cmd = plan.get("command", "")
                if cmd:
                    # Execute with inline verification + plan-repair
                    outcome = _execute_with_repair(cmd, plan, state)
                    results.append(outcome)
                    status = outcome.get("status", "error")

                    if _ledger:
                        try:
                            _ledger(
                                actor="mind_loop",
                                action="run_command",
                                rationale=plan.get("reason", "mind_loop plan action"),
                                predicted_outcome="success" if status == "ok" else "fail",
                                target="",
                                params={"command": cmd[:120], "returncode": outcome.get("returncode")},
                                triggered_by="mind_cycle",
                            )
                        except Exception:
                            pass
                    _record_feedback("command_execution", cmd[:100])
                    _record_narrative("action", cmd[:200], {
                        "domain": "infra",
                        "outcome": status,
                        "returncode": outcome.get("returncode"),
                    })
                    _register_verification("command_check", cmd[:100], {"command": cmd})
                    _record_self_outcome(action, status, conf)

                    # Escalation: if high-priority command failed, notify + budget
                    if status in ("error", "timeout") and plan.get("priority", 0) >= 8:
                        try:
                            import autonomous_self as _aslf
                            budget = _aslf.check_retry_budget("infra_command")
                            if budget["allowed"]:
                                _aslf.consume_retry("infra_command")
                                send_to_telegram(f"🛠️ Infra action failed: `{cmd[:80]}` — retry "
                                                 f"{budget['retries_used']+1}/{budget['budget']}. "
                                                 f"Escalating to autonomous_fixer.")
                            else:
                                send_to_telegram(f"🚨 Budget exhausted for `{cmd[:80]}` — manual intervention needed.")
                        except Exception:
                            pass

        except Exception as e:
            results.append({"action": action, "status": "error", "error": str(e)})
            log(f"Action failed: {action} — {e}", level="ERROR")
            _record_self_outcome(action, "failure", plan.get("confidence", 0.6))

    log(f"Execution: {len(results)} actions executed")
    return results


def _execute_with_repair(cmd: str, plan: dict, state: dict) -> dict:
    """Run a command; on failure, attempt a fallback diagnostic."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        status = "ok" if result.returncode == 0 else "error"
        if status == "ok":
            return {"action": "run_command", "status": "ok",
                    "returncode": result.returncode, "stdout_len": len(result.stdout)}
    except subprocess.TimeoutExpired:
        result = None
        status = "timeout"
    except Exception as e:
        return {"action": "run_command", "status": "error", "error": str(e), "returncode": -1}

    # Plan-repair: on failure, try a lighter fallback
    if status in ("error", "timeout") and plan.get("verify"):
        fallback = _repair_command(cmd, result)
        if fallback:
            log(f"Plan-repair: retrying {cmd!r} → fallback {fallback!r}")
            try:
                r2 = subprocess.run(fallback, shell=True, capture_output=True,
                                    text=True, timeout=15)
                if r2.returncode == 0:
                    return {"action": "run_command", "status": "ok_recovered",
                            "returncode": r2.returncode, "recovered": True,
                            "stdout_len": len(r2.stdout)}
            except Exception:
                pass

    return {"action": "run_command", "status": status,
            "returncode": result.returncode if result else -1,
            **(({"stdout_len": len(result.stdout)} if result else {}))}


def _repair_command(original: str, failed_result) -> str | None:
    """Suggest a fallback command for a failed one based on heuristics."""
    o = original.lower().strip()
    if "kopia snapshot list" in o:
        return "ls -la /mnt/usb/kopia-repo-volumes 2>/dev/null || echo 'kopia mount check'"
    if "git status" in o:
        return "git rev-parse --show-toplevel"
    if o.startswith("df"):
        return None
    if o.startswith("free"):
        return "cat /proc/meminfo | head -5"
    if o.startswith("uptime"):
        return None
    return None


def _record_narrative(etype: str, content: str, metadata: dict | None = None):
    """Record an event in episodic memory."""
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import narrative_memory as _nm
        _nm.store_episode({
            "type": etype,
            "content": content,
            "metadata": metadata or {},
        })
    except Exception as e:
        log(f"Narrative record error: {e}", level="WARN")


def _record_self_outcome(action: str, outcome: str, confidence: float | None = None):
    """Record action outcome for self-model confidence calibration."""
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import autonomous_self
        autonomous_self.record_action_outcome(action, outcome, confidence)
    except Exception:
        pass


def _propose_authoring_action(insight: dict, state: dict) -> dict | None:
    """
    Close the insight→done loop by proposing an authoring action (email reply,
    calendar event, command, Telegram message) for a cross-domain insight.
    Registers the proposal in the bridge's proposal queue so /send or /skip
    can execute/skip it. Returns a plan dict with action='send_telegram' (the
    preview message) + proposal_id for confirmation tracking.
    """
    content = insight.get("content", "").lower()
    suggestions = []

    # Actionable email → draft a reply template
    if "actionable" in content or "invoice" in content or "payment" in content:
        suggestions.append({
            "action": "send_email",
            "payload": {
                "to": "vendor@example.com",
                "subject": f"Re: {insight.get('content', '')[:60]}",
                "body": f"Hi,\n\nI noticed the invoice/payment reminder. I'll process this today and confirm back.\n\n— Hermes (on your behalf)",
            },
            "priority": 7,
            "tag": "email_draft",
        })

    # Calendar + email overlap → propose a meeting
    cal = state.get("last_signals", {}).get("calendar", {})
    email = state.get("last_signals", {}).get("email", {})
    if cal.get("upcoming") and email.get("has_actionable"):
        from datetime import timedelta
        now = datetime.now(timezone.utc) + timedelta(days=2)
        suggestions.append({
            "action": "create_event",
            "payload": {
                "summary": "Address actionable emails",
                "start": now.isoformat(),
                "end": (now + timedelta(minutes=30)).isoformat(),
                "description": "Block time to process pending actionable emails from last 24h.",
            },
            "priority": 6,
            "tag": "calendar_proposal",
        })

    # Streak break (wellness) → suggest break
    wellness = state.get("last_signals", {}).get("wellness", {})
    if wellness.get("stress_level", "") == "high":
        suggestions.append({
            "action": "send_telegram",
            "payload": {
                "content": "🧘‍♂️ Stress detected. Suggest: take a 10-min walk or deep-work break. Reply /done or /skip",
            },
            "priority": 5,
            "tag": "wellness_nudge",
        })

    if not suggestions:
        return None

    s = max(suggestions, key=lambda x: x["priority"])

    # Register proposal in the bridge queue
    proposal_id = None
    preview_text = None
    try:
        from n8n_bridge_server import handle_propose
        _topic = s.get("tag")
        mtid_map = {
            "email_draft": 7338,      # career-ops topic
            "calendar_proposal": 7343, # homelab topic
            "wellness_nudge": 7356,  # infra topic
        }
        result = handle_propose({
            "action": s["action"],
            "message_thread_id": mtid_map.get(s["tag"]),
            "category": s["tag"],
            **s["payload"],
        })
        proposal_id = result.get("proposal_id")
        preview_text = result.get("preview")
    except Exception as e:
        log(f"Proposal registration error: {e}", level="WARN")
        preview_text = s["payload"].get("content") or s["payload"].get("body", "")[:200]

    return {
        "action": "send_telegram",
        "content": preview_text or "Proposal ready (no preview)",
        "priority": s["priority"],
        "tag": s["tag"],
        "requires_confirm": True,
        "confidence": 0.5,
        "proposal_id": proposal_id,
    }


def _record_feedback(action_type: str, content: str):
    """Record an action in the feedback loop for outcome tracking."""
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import feedback_loop
        feedback_loop.record_action(action_type, content)
    except Exception:
        pass


def _register_verification(verify_method: str, target: str, params: dict):
    """Register an action for self-correction verification."""
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import self_correction as sc
        state = sc.load_state()
        state["pending_verifications"].append({
            "type": "auto",
            "target": target,
            "verify_method": verify_method,
            "verify_params": params,
            "created": datetime.now(timezone.utc).isoformat(),
            "verify_after": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        })
        sc.save_state(state)
    except Exception:
        pass


def _send_proposal_telegram(proposal: dict):
    """Send a sub-agent proposal to Telegram with confirm/skip hint."""
    detail = proposal.get("detail", {})
    text = detail.get("summary") or detail.get("subject") or proposal.get("text", "")
    body = detail.get("body", "")
    if body:
        text = f"{text}\n\n{body}"
    confirm_cmd = detail.get("confirm_cmd", "")
    if confirm_cmd:
        text += f"\n\n✅ {confirm_cmd}  ❌ /skip"
    send_to_telegram(text)
    _record_feedback("proposal_shown", text[:120])


def _run_autoself_fixer():
    """Trigger autonomous_fixer for sub-agent failures."""
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import autonomous_fixer as _af
        _af.run_fix_cycle() if hasattr(_af, 'run_fix_cycle') else None
        log("Autonomous fixer triggered via reconciliation escalation")
    except Exception as e:
        log(f"Auto-fixer trigger error: {e}", level="ERROR")


def send_to_telegram(message: str):
    """Send a message to Telegram via bridge, with deduplication."""
    # Dedup check — don't send the same message repeatedly
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        from send_dedup import is_duplicate, register_send
        if is_duplicate(message):
            log(f"Skipping duplicate message: {message[:60]}...")
            return
    except Exception:
        pass  # If dedup fails, send anyway

    # Send via bridge
    try:
        from telegram_bridge import send_telegram
        send_telegram(message)
        register_send(message)
        return
    except Exception:
        pass  # Fall through to CLI fallback

    # Fallback: hermes CLI subprocess
    hermes_bin = os.path.expanduser("~/.local/bin/hermes")
    if not os.path.exists(hermes_bin):
        hermes_bin = "hermes"
    subprocess.run(
        [hermes_bin, "send", "-t", "telegram", message],
        capture_output=True, text=True, timeout=30,
    )
    # Register successful send
    try:
        register_send(message)
    except Exception:
        pass


def compose_morning_briefing(state: dict) -> str:
    """Compose a morning briefing message."""
    now = datetime.now().strftime("%A, %B %d — %H:%M")
    parts = [f"☀️ **Good Morning!** {now}\n"]

    # Add health summary
    health = state.get("last_signals", {}).get("health", {})
    score = health.get("score", "?")
    parts.append(f"🏥 Health: {score}/100")

    # Add email summary
    email = state.get("last_signals", {}).get("email", {})
    if email.get("has_actionable"):
        parts.append("📬 Actionable emails waiting")

    # Add top insight
    insights = state.get("insights", [])
    if insights:
        latest = insights[-1]
        parts.append(f"💡 {latest.get('content', '')[:100]}")

    return "\n".join(parts)


def task_queue_add(title: str, priority: int = 5):
    """Add a task to the persistent task queue."""
    try:
        subprocess.run(
            ["python3", str(HERMES_HOME / "scripts/task_queue.py"),
             "add", "--title", title, "--priority", str(priority)],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        log(f"Failed to add task: {e}", level="ERROR")


# ---------------------------------------------------------------------------
# REFLECT: Learn from actions
# ---------------------------------------------------------------------------
def reflect(state: dict, signals: dict, insights: list, plans: list, results: list) -> dict:
    """Reflect on the cycle: what worked, what didn't, what did we learn."""
    reflection = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle": state.get("cycle_count", 0),
        "insights_generated": len(insights),
        "actions_planned": len(plans),
        "actions_executed": len(results),
        "errors": sum(1 for r in results if r.get("status") == "error"),
        "learnings": [],
    }

    # Learning: track what types of insights lead to actions
    for insight in insights:
        if insight.get("action_suggested") == "surface_to_telegram":
            reflection["learnings"].append(
                f"Cross-domain insight: {insight['content'][:80]}"
            )

    # Learning: track health trends
    health = signals.get("health", {})
    score = health.get("score")
    if score is not None:
        history = state.get("health_history", [])
        history.append({"timestamp": datetime.now(timezone.utc).isoformat(), "score": score})
        state["health_history"] = history[-100:]  # keep last 100

        if len(history) >= 3:
            recent = [h["score"] for h in history[-3:]]
            if all(r < 80 for r in recent):
                reflection["learnings"].append("Health score declining over last 3 cycles")

    log(f"Reflection: {len(reflection['learnings'])} learnings captured")
    return reflection


# ---------------------------------------------------------------------------
# EVOLVE: Update goals and strategies
# ---------------------------------------------------------------------------
def evolve(state: dict, reflection: dict):
    """Evolve the agent's goals and strategies based on reflections."""
    # Add new goals based on patterns
    for learning in reflection.get("learnings", []):
        if "declining" in learning.lower():
            goal = {
                "id": hashlib.md5(learning.encode()).hexdigest()[:8],
                "title": "Investigate health decline",
                "created": datetime.now(timezone.utc).isoformat(),
                "status": "active",
                "source": "mind_loop_auto",
            }
            existing_titles = {g["title"] for g in state.get("goals", [])}
            if goal["title"] not in existing_titles:
                state.setdefault("goals", []).append(goal)
                log(f"New goal created: {goal['title']}")

    # Prune completed/old goals
    state["goals"] = [
        g for g in state.get("goals", [])
        if g.get("status") == "active"
    ][:20]  # keep max 20 active goals


# ---------------------------------------------------------------------------
# Main cycle
# ---------------------------------------------------------------------------
def run_cycle():
    """Run one complete mind loop cycle."""
    tracer = _tracer
    state = load_state()
    state["cycle_count"] = state.get("cycle_count", 0) + 1
    cycle_num = state["cycle_count"]

    log(f"{'='*60}")
    log(f"Starting mind loop cycle #{cycle_num}")
    log(f"{'='*60}")

    with tracer.span("mind_loop_cycle") as cycle_span:
        cycle_span.set_attribute("cycle", cycle_num)

        # Update GNAP heartbeat
        if _gnap_agent:
            _gnap_agent.register()

        # 1. OBSERVE
        with tracer.span("observe", parent=cycle_span) as obs_span:
            signals = run_observation()
            signals = mind_loop_integration.observe_intelligence(signals)
            state["last_signals"] = signals
            obs_span.set_attribute("signal_count", sum(len(v) if isinstance(v, (list, dict)) else 0 for v in signals.values()))

        # 2. CONNECT
        with tracer.span("connect", parent=cycle_span) as conn_span:
            insights = find_patterns(state, signals)
            insights = mind_loop_integration.connect_intelligence(state, signals, insights)
            state["insights"] = (state.get("insights", []) + insights)[-50:]
            for ins in insights:
                append_insight(ins)
            conn_span.set_attribute("insight_count", len(insights))

            # Enhanced: GraphRAG cross-domain (every 3rd cycle)
            if _graphrag and cycle_num % 3 == 0:
                try:
                    for domain_signal in signals.get("external", {}).get("hn_trending", [])[:3]:
                        ctx = _graphrag.query(str(domain_signal), max_hops=1)
                        if ctx.entities:
                            insights.append({"type": "graphrag", "content": f"Graph context: {len(ctx.entities)} entities related to trend", "severity": "info"})
                except Exception:
                    pass

        # 3. ANTICIPATE
        with tracer.span("anticipate", parent=cycle_span) as ant_span:
            anticipations = anticipate(state, signals, insights)
            anticipations = mind_loop_integration.anticipate_intelligence(state, signals, insights, anticipations)
            ant_span.set_attribute("anticipation_count", len(anticipations))

        # 4. PLAN
        with tracer.span("plan", parent=cycle_span) as plan_span:
            plans = create_plan(insights, anticipations, state=state)
            plans = mind_loop_integration.plan_intelligence(insights, anticipations, plans)
            plan_span.set_attribute("plan_count", len(plans))

        # 5. ACT  — execute plans via multi-agent sub-specialists
        with tracer.span("act", parent=cycle_span) as act_span:
            all_results = []
            for plan in plans:
                # Decompose plan into sub-tasks + dispatch to specialist agents
                if _NEW_MODULES:
                    try:
                        from agent_orchestrator import dispatch_plan
                        sub_results = dispatch_plan(plan)
                        all_results.extend(sub_results)
                    except Exception as e:
                        log(f"Orchestrator dispatch error for plan: {e}", level="WARN")
                        # Fallback: execute plan directly
                        single = execute_plan([plan], state)
                        all_results.extend(single)
                else:
                    single = execute_plan([plan], state)
                    all_results.extend(single)

            state["action_history"] = (state.get("action_history", []) + all_results)[-100:]
            act_span.set_attribute("action_count", len(all_results))

            # 5b. Reconcile sub-agent results + surface proposals
            if _NEW_MODULES:
                try:
                    from agent_orchestrator import reconcile_and_surface
                    rec = reconcile_and_surface(all_results)
                    state["last_reconciliation"] = rec
                    # Surface any proposals as Telegram-confirm messages
                    for prop in rec.get("proposals", []):
                        _send_proposal_telegram(prop)
                    # Escalate failures
                    for fu in rec.get("follow_ups", []):
                        if fu["action"] == "escalate":
                            log(f"Escalating {fu.get('reason')} to autonomous_fixer")
                            try:
                                _run_autoself_fixer()
                            except Exception:
                                pass
                except Exception as e:
                    log(f"Reconciliation error: {e}", level="WARN")

            # Record quality metrics
            if _quality_tracker:
                for action in [a for a in state.get("action_history", [])[-5:] if a.get("status") == "ok"]:
                    _quality_tracker.record_action(
                        domain="INFRA" if "command" in str(action.get("action", "")) else "PERSONAL",
                        proactive=True,
                        outcome=action.get("status", "unknown"),
                    )

        # 6. REFLECT
        with tracer.span("reflect", parent=cycle_span) as ref_span:
            reflection = reflect(state, signals, insights, plans, all_results)
            state["reflection_log"] = (state.get("reflection_log", []) + [reflection])[-50:]
            ref_span.set_attribute("reflection_count", len(reflection.get("learnings", [])))

        # 7. EVOLVE
        with tracer.span("evolve", parent=cycle_span) as ev_span:
            evolve(state, reflection)

        # 8. CROSS-DOMAIN INSIGHTS (every 3rd cycle)
        if _NEW_MODULES and cycle_num % 3 == 0:
            try:
                deep_insights = insight_engine.run_insight_engine(top_n=3)
                if deep_insights:
                    state["deep_insights"] = [
                        {"type": i["type"], "content": i["content"][:100], "timestamp": datetime.now(timezone.utc).isoformat()}
                        for i in deep_insights
                    ]
                    for di in deep_insights:
                        if di.get("severity") == "high":
                            feedback_loop.record_action("insight_engine", di["content"][:200])
                    log(f"Deep insights: {len(deep_insights)} found")
            except Exception as e:
                log(f"Insight engine error: {e}", level="ERROR")

    # 9. PERSONAL MODEL UPDATE (every cycle — lightweight goal decay + goal-action planning)
    if _NEW_MODULES:
        try:
            pm_state = personal_model._load_state()
            goals = personal_model.decay_and_reprioritise(pm_state)
            state["life_goals"] = goals
            state["personal_model_summary"] = {
                "peak_hours": pm_state.get("work_patterns", {}).get("peak_hours", []),
                "stress": pm_state.get("stress_indicators", {}).get("current_stress_level", "unknown"),
                "unspoken_needs": len(pm_state.get("unspoken_needs", [])),
                "values": list(pm_state.get("values", {}).keys())[:5],
            }
            log(f"Personal model: {len(goals)} life goals active")
        except Exception as e:
            log(f"Personal model error: {e}", level="ERROR")

        # Store in unified memory
        if _memory:
            try:
                _memory.store("personal_model", state.get("personal_model_summary", {}),
                              domain="PERSONAL", key=f"pm_{datetime.now().strftime('%Y%m%d%H%M')}")
            except Exception:
                pass

    # 10. NARRATIVE MEMORY UPDATE (every 10th cycle)
    if _NEW_MODULES and cycle_num % 10 == 0:
        try:
            nm = narrative_memory.update_narratives()
            state["narrative_count"] = len(nm.get("narratives", []))
            log(f"Narrative memory: {len(nm.get('narratives', []))} stories")
        except Exception as e:
            log(f"Narrative memory error: {e}", level="ERROR")

    # 11. FEEDBACK LOOP CHECK (every cycle)
    if _NEW_MODULES:
        try:
            feedback_loop.check_action_outcomes(feedback_loop.load_feedback())
        except Exception as e:
            log(f"Feedback loop error: {e}", level="ERROR")

    # 12. AUTONOMOUS SELF REFLECTION (every 5th cycle — self-health + self-goals)
    if _NEW_MODULES and cycle_num % 5 == 0:
        try:
            import autonomous_self
            self_result = autonomous_self.run_self_reflection()
            goals = self_result.get("self_goals", [])
            health = self_result.get("last_analysis", {}).get("overall_health", "?")
            state["self_health"] = health
            state["self_goals_count"] = len(goals)
            log(f"Self-reflection: health={health}, goals={len(goals)}")
        except Exception as e:
            log(f"Autonomous self error: {e}", level="ERROR")

    # Track quality metrics for the cycle
    if _quality_tracker:
        _quality_tracker.record_interaction(
            domain="mind_loop",
            latency_ms=0,
            resolved=len(all_results) > 0,
            tokens_used=0,
        )
        telos = _quality_tracker.get_telos_score()
        state["telos_score"] = telos.get("score", 0)
        if telos.get("score", 100) < 90:
            log(f"TELOS score: {telos['score']}/100 — below target", level="WARN")

    # Save state
    save_state(state)

    log(f"Cycle #{cycle_num} complete. Insights: {len(insights)}, Actions: {len(all_results)}")
    return state


def run_daemon(interval_minutes: int = 30):
    """Run the mind loop continuously."""
    log(f"Mind loop daemon starting. Interval: {interval_minutes} minutes")
    while True:
        try:
            run_cycle()
        except Exception as e:
            log(f"Cycle error: {e}", level="ERROR")
        log(f"Sleeping {interval_minutes} minutes...")
        time.sleep(interval_minutes * 60)


def show_status():
    """Display current mind state."""
    state = load_state()
    print(f"\n{'='*60}")
    print(f"  Hermes Mind Loop — Status")
    print(f"{'='*60}")
    print(f"  Cycles run: {state.get('cycle_count', 0)}")
    print(f"  Last cycle: {state.get('last_cycle', 'never')}")
    print(f"  Active goals: {len(state.get('goals', []))}")
    print(f"  Total insights: {len(state.get('insights', []))}")
    print(f"  Reflections: {len(state.get('reflection_log', []))}")

    if state.get("insights"):
        print(f"\n  Latest insights:")
        for ins in state["insights"][-5:]:
            print(f"    • [{ins.get('type', '?')}] {ins.get('content', '')[:80]}")

    if state.get("goals"):
        print(f"\n  Active goals:")
        for g in state["goals"][-5:]:
            print(f"    • {g.get('title', '?')}")

    # Last signals
    last = state.get("last_signals", {})
    if last:
        health = last.get("health", {})
        print(f"\n  Last health score: {health.get('score', '?')}/100")
        failed = [n for n, c in health.get("checks", {}).items() if c.get("status") not in ("ok", "healthy")]
        if failed:
            print(f"  Issues: {', '.join(failed)}")

    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if "--daemon" in sys.argv:
        interval = 5
        for i, arg in enumerate(sys.argv):
            if arg == "--interval" and i + 1 < len(sys.argv):
                interval = int(sys.argv[i + 1])
        run_daemon(interval)
    elif "--status" in sys.argv:
        show_status()
    elif "--insight" in sys.argv:
        state = load_state()
        signals = run_observation()
        insights = find_patterns(state, signals)
        for ins in insights:
            print(f"[{ins.get('type', '?')}] {ins.get('content')}")
    else:
        run_cycle()
