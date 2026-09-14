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
            cycle_interval_minutes=30,
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
        # Keep recent only
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
                signals["board"] = board.get("tasks", {})
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
        
        # Cross-agent coordination needs (dedup: only NEW ready tasks)
        ready = signals.get("ready_tasks", [])
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
                    results.append({"action": "delegate", "status": "ok", "detail": result})
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