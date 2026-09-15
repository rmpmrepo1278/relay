#!/usr/bin/env python3
"""
jenny_agent.py — Chief of Staff autonomous agent.

Jenny owns the agent org coordination: onboarding, cross-agent task management,
daily briefings, playbook reviews, wiring changes.
"""

from __future__ import annotations

from autonomous_agent import AutonomousAgent, _log
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import json
import os
from pathlib import Path


class JennyAgent(AutonomousAgent):
    """Chief of Staff — owns org coordination, onboarding, cross-agent tasks."""
    
    def __init__(self):
        super().__init__(
            name="jenny",
            domain="coordination",
            topic_id=10000,  # Coordination topic
            cycle_interval_minutes=1,
        )
        self.org_roster = self._load_roster()
        self.mem_root = Path.home() / ".hermes" / "collaborator-memory"
    
    def _load_roster(self) -> dict:
        """Load current org roster from playbook."""
        try:
            import yaml
            p = Path.home() / ".hermes" / "collaborator-memory" / "memory" / "jenny.md"
            if p.exists():
                with open(p) as f:
                    content = f.read()
                return {"loaded": True, "path": str(p)}
            return {"loaded": False, "note": "roster file not found"}
        except Exception as e:
            return {"loaded": False, "error": str(e)}
    
    def _is_handled(self, key: str, ttl_hours: int = 24) -> bool:
        """True if this key was handled within the TTL window."""
        last = self.state.get("handled", {}).get(key)
        if not last:
            return False
        try:
            ts = datetime.fromisoformat(last)
            return datetime.now(timezone.utc) - ts < timedelta(hours=ttl_hours)
        except Exception:
            return False

    def _mark_handled(self, key: str):
        handled = self.state.setdefault("handled", {})
        handled[key] = datetime.now(timezone.utc).isoformat()
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        self.state["handled"] = {
            k: v for k, v in handled.items()
            if self._parse_ts(v) and self._parse_ts(v) >= cutoff
        }

    @staticmethod
    def _parse_ts(iso: str):
        try:
            return datetime.fromisoformat(iso)
        except Exception:
            return None

    def _looks_like_greeting(self, title: str) -> bool:
        """True when the user's message is Jenny-chat, not a delegation order."""
        low = title.lower().strip()
        words = len(low.split())
        chat_tokens = ["hi", "hey", "hello", "yo", "how are you", "what's up", "whats up",
                       "sup", "thanks", "thank you", "good job", "well done", "great work",
                       "who are you", "what do you do", "good morning", "good evening",
                       "nice", "awesome", "cool", "good"]
        if any(tok in low for tok in chat_tokens) and words <= 8:
            return True
        if "jenny" in low and words <= 3:
            return True
        return False

    def _assess_message(self, title: str) -> str:
        """Assess whether Jenny should respond directly or delegate to a specialist.

        Returns one of:
        - 'respond': Jenny can handle this directly (greetings, small talk, simple queries)
        - 'delegate': A specialist agent is more appropriate
        - 'coordinate': Multi-agent coordination needed
        """
        low = title.lower().strip()

        # 1. Greetings & small talk → Jenny responds directly
        if self._looks_like_greeting(title):
            return "respond"

        # 2. Jenny's direct competence domains → respond
        # Brief-related
        if any(tok in low for tok in ["brief", "org brief", "daily brief", "weekly brief"]):
            return "respond"
        # Onboarding
        if any(tok in low for tok in ["onboard", "introduce", "welcome new"]):
            return "respond"
        # Coordination overview
        if any(tok in low for tok in ["team", "roster", "status overview"]):
            return "respond"

        # 3. Specialist domains → delegate (Jenny's competence boundary)
        # Homelab/Docker/containers/systemd
        homelab_keywords = ["docker", "container", "systemd", "kubernetes", "homelab",
                            "disk", "memory", "backup", "health check", "status",
                            "restart", "update", "disk cleanup"]
        if any(tok in low for tok in homelab_keywords):
            # Jenny can coordinate but specialized agents handle deep domain work
            return "delegate"

        # Finlay/Finance
        finlay_keywords = ["finance", "bill", "bank", "payment", "subscription",
                           "budget", "expense", "invoice", "cost", "refund"]
        if any(tok in low for tok in finlay_keywords):
            return "delegate"

        # Calendula/Health
        calendula_keywords = ["calendar", "appointment", "medication", "refill",
                              "doctor", "vaccine", "health check", "symptoms"]
        if any(tok in low for tok in calendula_keywords):
            return "delegate"

        # Connector/Telegram/Notifications
        connector_keywords = ["telegram", "notify", "digest", "topic", "broadcast",
                              "message", "send message"]
        if any(tok in low for tok in connector_keywords):
            return "delegate"

        # 4. Coordination/meta-tasks → coordinate or delegate
        if any(tok in low for tok in ["coordinate", "delegate", "assign", "handoff"]):
            # Jenny can coordinate but may delegate execution
            return "coordinate"

        # 5. Unknown/complex → delegate (safe default)
        return "delegate"

    def _mark_task_ended(self, key: str, status: str, proof: str = ""):
        """Set a bus task to a terminal state (done/failed) via POST JSON."""
        import urllib.request
        payload = json.dumps({"op": "set", "key": key, "status": status,
                              "owner": "jenny", "proof": proof}).encode()
        req = urllib.request.Request("http://127.0.0.1:9107/task", data=payload,
                                     method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=4).read()
        except Exception:
            pass

    def _friendly_reply(self, title: str) -> str:
        """A warm Chief-of-Staff response for small-talk from Rohit."""
        low = title.lower()
        if any(tok in low for tok in ["how are you", "how's it going", "how's going"]):
            return ("👋 All good, Rohit! Team's healthy — 10 agents reporting, "
                    "Jenny coordinating. Anything you want me to delegate?")
        if any(tok in low for tok in ["what do you do", "what can you do", "who are you", "what are you"]):
            return ("👋 I'm Jenny — your Chief of Staff. I coordinate the homelab team, "
                    "run daily org briefs, and you can /delegate tasks to specialists "
                    "or /jenny me directly. Try /team to see everyone.")
        if any(tok in low for tok in ["thanks", "thank you", "good job", "well done", "nice work"]):
            return "😊 Anytime, Rohit! Happy to help — the team's got your back."
        if "jenny" in low or "hi" in low or "hey" in low or "hello" in low:
            return ("👋 Hey Rohit! Jenny here — Chief of Staff. "
                    "Team's running smooth: /team to see status, "
                    "or just tell me what you need handled and I'll delegate it.")
        return ("👋 Hey Rohit! Ready when you are. "
                "Give me a task like \"follow up on the electricity bill\" and I'll route it "
                "to the right specialist — or /team for the roster.")

    def _route_directive(self, title: str) -> str:
        low = title.lower()
        table = [
            ("inference",   ["model", "llm", "provider", "inference", "haiku", "benchmark"]),
            ("finlay",      ["finance", "bill", "bank", "payment", "subscription", "budget", "expense"]),
            ("housekeep",   ["filter", "clean", "appliance", "clog", "vacuum", "air"]),
            ("calendula",   ["calendar", "appointment", "medication", "refill", "doctor", "vaccine"]),
            ("connector",   ["birthday", "anniversary", "contact", "gift", "friend", "family"]),
            ("homelab",     ["disk", "network", "update", "restart", "health check", "status", "how"]),
            ("baseplate",   ["container", "deploy", "docker", "systemd", "uptime", "backup"]),
            ("vault",       ["memory", "backup", "journal", "knowledge", "data", "sync"]),
            ("courier",     ["notify", "telegram", "digest", "topic", "broadcast"]),
        ]
        for agent, keys in table:
            if any(k in low for k in keys):
                return agent
        return "homelab"  # safe default for infra-oriented team
    
    # ─── OBSERVE ─────────────────────────────────────────────────────────────
    
    def observe(self) -> dict:
        """Gather org-wide signals: agentbus status, task board, objectives, journal."""
        import urllib.request, urllib.parse
        
        signals = {}
        
        # Agentbus status
        try:
            with urllib.request.urlopen("http://127.0.0.1:9107/status", timeout=5) as resp:
                bus = json.loads(resp.read().decode())
                signals["agentbus"] = bus
        except Exception as e:
            signals["agentbus"] = {"error": str(e)}
        
        # Task board
        try:
            with urllib.request.urlopen("http://127.0.0.1:9107/board", timeout=5) as resp:
                board = json.loads(resp.read().decode())
                tasks = board.get("tasks", {})
                if isinstance(tasks, dict):
                    tasks = {tk: {**tv, "key": tk} for tk, tv in tasks.items()}
                signals["board"] = tasks
        except Exception as e:
            signals["board"] = {"error": str(e)}
        
        # Objectives
        signals["objectives"] = signals.get("agentbus", {}).get("objectives", {})
        
        # Presence
        signals["presence"] = signals.get("agentbus", {}).get("presence", {})
        
        # Claims
        signals["claims"] = signals.get("agentbus", {}).get("claims", {})
        
        # Latest journal
        import glob
        jdir = str(self.mem_root / "journal")
        if os.path.exists(jdir):
            files = glob.glob(os.path.join(jdir, "*.md"))
            if files:
                latest = max(files, key=os.path.getmtime)
                try:
                    with open(latest) as f:
                        signals["latest_journal"] = f.read()[:2000]
                except Exception:
                    pass
        
        # Cross-agent task readiness
        tasks = signals.get("board", {})
        ready_tasks = [t for t in tasks.values() if t.get("status") == "ready"]
        overdue_tasks = []
        for t in tasks.values():
            due = t.get("due", "")
            if due:
                try:
                    if datetime.fromisoformat(due).date() <= datetime.now().date():
                        overdue_tasks.append(t)
                except Exception:
                    pass
        
        signals["ready_tasks"] = ready_tasks
        signals["overdue_tasks"] = overdue_tasks
        signals["timestamp"] = datetime.now(timezone.utc).isoformat()
        
        return signals
    
    # ─── CONNECT ─────────────────────────────────────────────────────────────
    
    def connect(self, signals: dict) -> list:
        """Generate insights from org signals (deduplicated by handled keys)."""
        insights = []
        
        # User directives for Jenny (from bridge /jenny <instruction>)
        ready = signals.get("ready_tasks", [])
        for task in ready:
            owner = task.get("owner", "unknown")
            area = task.get("area", "unknown")
            if (owner in ("rohit", "user", "me") and area == "jenny"):
                key = f"directive:{task.get('key') or task.get('title')}"
                if self._is_handled(key):
                    continue
                insights.append({
                    "type": "user_directive",
                    "content": f"Rohit directive: {task.get('title')}",
                    "action_suggested": "user_directive",
                    "severity": "high",
                    "source_task": task,
                    "dedup_key": key,
                })

        # Cross-agent coordination needs (dedup: only NEW ready tasks)
        for task in ready:
            owner = task.get("owner", "unknown")
            area = task.get("area", "unknown")
            if owner != "jenny" and area != "coordination":
                key = f"coord:{task.get('key') or task.get('title')}"
                if self._is_handled(key):
                    continue
                insights.append({
                    "type": "coordination_needed",
                    "content": f"Task '{task.get('title')}' by {owner} in {area} is ready — needs coordination",
                    "action_suggested": "coordinate",
                    "severity": "medium",
                    "source_task": task,
                    "dedup_key": key,
                })
        
        # Overdue items (dedup)
        overdue = signals.get("overdue_tasks", [])
        for task in overdue:
            key = f"overdue:{task.get('key') or task.get('title')}"
            if self._is_handled(key):
                continue
            insights.append({
                "type": "overdue_alert",
                "content": f"Overdue task: {task.get('title')} (owner: {task.get('owner')}, due: {task.get('due')})",
                "action_suggested": "escalate",
                "severity": "high",
                "source_task": task,
                "dedup_key": key,
            })
        
        # Agent health (dedup: only flag each agent once per TTL)
        presence = signals.get("presence", {})
        expected_agents = ["homelab", "finlay", "housekeep", "calendula", "connector"]
        for agent in expected_agents:
            if agent not in presence:
                key = f"missing:{agent}"
                if self._is_handled(key, ttl_hours=6):
                    continue
                insights.append({
                    "type": "agent_missing",
                    "content": f"Agent {agent} not reporting on bus",
                    "action_suggested": "check_agent",
                    "severity": "medium",
                    "dedup_key": key,
                })
        
        # Onboarding requests (dedup)
        claims = signals.get("agentbus", {}).get("claims", {})
        for claim in claims.values():
            if "onboard" in claim.get("note", "").lower():
                key = f"onboard:{claim.get('note')}"
                if self._is_handled(key, ttl_hours=48):
                    continue
                insights.append({
                    "type": "onboarding_request",
                    "content": f"Onboarding request: {claim.get('note')}",
                    "action_suggested": "onboard",
                    "severity": "high",
                    "dedup_key": key,
                })
        
        return insights
    
    # ─── ANTICIPATE ──────────────────────────────────────────────────────────
    
    def anticipate(self, signals: dict, insights: list) -> list:
        """Predict coordination needs."""
        anticipations = []
        
        # If bills due soon, anticipate Finlay → Homelab coordination
        # (handled by Finlay agent, but Jenny anticipates cross-agent needs)
        
        # If agents missing, anticipate health check (deduped)
        presence = signals.get("presence", {})
        missing = [a for a in ["homelab", "finlay", "housekeep", "calendula", "connector"] if a not in presence]
        for agent in missing:
            key = f"missing:{agent}"
            if not self._is_handled(key, ttl_hours=6):
                self.delegate_to_agent(agent, f"health_check: {agent} not reporting", priority=7)
                self._mark_handled(key)
        
        # Anticipate daily brief
        now = datetime.now()
        if now.hour == 4 and now.minute >= 45:  # Before 5am brief
            self.send_to_own_topic("📋 Preparing 05:00 org brief...")
        
        return []
    
    # ─── PLAN ────────────────────────────────────────────────────────────────
    
    def plan(self, signals: dict, insights: list, anticipations: list) -> list:
        """Create coordination plans."""
        plans = []
        
        # Process insights into actions
        for insight in insights:
            action = insight.get("action_suggested")
            severity = insight.get("severity", "medium")
            priority = {"critical": 10, "high": 8, "medium": 5, "low": 3}.get(severity, 5)
            
            if action == "coordinate":
                task = insight.get("source_task", {})
                plans.append({
                    "action": "coordinate_cross_agent",
                    "content": f"Coordinate {task.get('owner')} on '{task.get('title')}'",
                    "priority": priority,
                    "source_insight": insight.get("content", "")[:80],
                    "confidence": 0.8,
                    "dedup_key": insight.get("dedup_key"),
                })
            elif action == "escalate":
                plans.append({
                    "action": "send_telegram",
                    "content": f"🚨 ESCALATION: {insight.get('content')}",
                    "priority": 10,
                    "confidence": 0.9,
                    "dedup_key": insight.get("dedup_key"),
                })
            elif action == "check_agent":
                agent = insight.get("content", "").split()[-1] if insight.get("content") else "unknown"
                plans.append({
                    "action": "delegate",
                    "target": agent,
                    "content": f"health_check: {agent} not reporting on bus",
                    "priority": 7,
                    "confidence": 0.7,
                    "dedup_key": insight.get("dedup_key"),
                })
            elif action == "user_directive":
                title = insight.get("source_task", {}).get("title", "")
                assessment = self._assess_message(title)
                if assessment == "respond":
                    # Jenny handles this directly (greetings, small talk, simple queries)
                    plans.append({
                        "action": "reply_chat",
                        "content": title,
                        "priority": 6,
                        "confidence": 0.95,
                        "dedup_key": insight.get("dedup_key"),
                        "source_task": insight.get("source_task", {}),
                    })
                elif assessment == "delegate":
                    # A specialist agent is more appropriate → delegate as before
                    if self._looks_like_greeting(title):
                        plans.append({
                            "action": "reply_chat",
                            "content": title,
                            "priority": 6,
                            "confidence": 0.95,
                            "dedup_key": insight.get("dedup_key"),
                            "source_task": insight.get("source_task", {}),
                        })
                    else:
                        agent = self._route_directive(title)
                        plans.append({
                            "action": "delegate",
                            "target": agent,
                            "content": title,
                            "priority": 8,
                            "confidence": 0.7,
                            "dedup_key": insight.get("dedup_key"),
                            "source_task": insight.get("source_task", {}),
                        })
                elif assessment == "coordinate":
                    # Multi-agent coordination needed
                    plans.append({
                        "action": "coordinate_cross_agent",
                        "content": f"Jenny to coordinate: {title}",
                        "priority": 7,
                        "confidence": 0.8,
                        "dedup_key": insight.get("dedup_key"),
                        "source_task": insight.get("source_task", {}),
                    })
            elif action == "onboard":
                plans.append({
                    "action": "initiate_onboarding",
                    "content": f"Process onboarding: {insight.get('content')}",
                    "priority": 10,
                    "confidence": 0.9,
                    "dedup_key": insight.get("dedup_key"),
                })
        
        # Daily brief at 5am
        now = datetime.now()
        if now.hour == 4 and now.minute >= 55:
            plans.append({
                "action": "generate_brief",
                "content": "Generate and send 05:00 org brief",
                "priority": 10,
                "confidence": 1.0,
            })
        
        return plans
    
    # ─── ACT ──────────────────────────────────────────────────────────────────
    
    MAX_ACTIONS_PER_CYCLE = 8
    
    def act(self, plans: list, signals: dict) -> list:
        """Execute coordination plans (capped per cycle, deduplicated)."""
        results = []
        sent = 0
        
        for plan in plans:
            if sent >= self.MAX_ACTIONS_PER_CYCLE:
                break
            action = plan.get("action")
            dedup_key = plan.get("dedup_key")
            try:
                if action == "send_telegram":
                    self.send_to_own_topic(plan.get("content", ""))
                    results.append({"action": "send_telegram", "status": "ok"})
                    if dedup_key:
                        self._mark_handled(dedup_key)
                    sent += 1
                
                elif action == "coordinate_cross_agent":
                    content = plan.get("content", "")
                    self.publish_to_bus("coordination", "coordinate", content)
                    self.send_to_own_topic(f"📋 Coordinating: {plan.get('content')}")
                    results.append({"action": "coordinate_cross_agent", "status": "ok"})
                    if dedup_key:
                        self._mark_handled(dedup_key)
                    sent += 1
                
                elif action == "delegate":
                    target = plan.get("target")
                    content = plan.get("content", "")
                    result = self.delegate_to_agent(target, content, priority=7)
                    if isinstance(plan, dict) and plan.get("source_task"):
                        src = plan["source_task"]
                        key = src.get("key")
                        if key:
                            self._mark_task_ended(key, "done", f"delegated_to:{target}")
                        self.send_to_own_topic(
                            f"📤 Delegated to *{target}*: {content[:80]}...")
                    results.append({"action": "delegate", "status": "ok", "detail": result})
                    if dedup_key:
                        self._mark_handled(dedup_key)
                    sent += 1
                
                elif action == "reply_chat":
                    content = plan.get("content", "")
                    greeting = self._friendly_reply(content)
                    self.send_to_own_topic(greeting)
                    if isinstance(plan, dict) and plan.get("source_task"):
                        key = plan["source_task"].get("key")
                        if key:
                            self._mark_task_ended(key, "done", "replied_to_rohit")
                    results.append({"action": "reply_chat", "status": "ok"})
                    if dedup_key:
                        self._mark_handled(dedup_key)
                    sent += 1

                elif action == "initiate_onboarding":
                    content = plan.get("content", "")
                    self.send_to_own_topic(f"🎯 Onboarding initiated: {content}")
                    self.publish_to_bus("coordination", "onboard", content)
                    results.append({"action": "initiate_onboarding", "status": "ok"})
                    if dedup_key:
                        self._mark_handled(dedup_key)
                    sent += 1
                
                elif action == "generate_brief":
                    import subprocess
                    result = subprocess.run(
                        ["python3", "/home/rohit/.hermes/agentbus/jenny_brief.py", "--now"],
                        capture_output=True, text=True, timeout=30
                    )
                    if result.returncode == 0:
                        results.append({"action": "generate_brief", "status": "ok"})
                    else:
                        results.append({"action": "generate_brief", "status": "error", "error": result.stderr})
                    sent += 1
                
                else:
                    results.append({"action": action, "status": "unknown"})
                    
            except Exception as e:
                results.append({"action": plan.get("action"), "status": "error", "error": str(e)})
        
        return results


if __name__ == "__main__":
    import sys
    agent = JennyAgent()
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        agent.run_daemon()
    else:
        print(json.dumps(agent.run_cycle(), indent=2))