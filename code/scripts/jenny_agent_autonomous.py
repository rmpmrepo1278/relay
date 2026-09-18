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
import re
import time
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
        # Fail-closed guardrail overrides (optional YAML, see guardrails.py).
        self._guardrails_override = {}
        try:
            from guardrails import load_guardrails
            g = load_guardrails("jenny")
            if g.get("extra_delegate_targets"):
                self._DELEGATE_TARGETS = tuple(self._DELEGATE_TARGETS) + tuple(g["extra_delegate_targets"])
            if g.get("extra_plan_actions"):
                self._PLAN_ACTIONS = tuple(self._PLAN_ACTIONS) + tuple(g["extra_plan_actions"])
            if g.get("cooldown_min"):
                self._PLAN_COOLDOWN_MIN = dict(self._PLAN_COOLDOWN_MIN)
                self._PLAN_COOLDOWN_MIN.update({k: float(v) for k, v in g["cooldown_min"].items()})
            if g.get("max_plans"):
                self._MAX_PLANS = g["max_plans"]
            w = g.get("brief_window")
            if isinstance(w, list) and len(w) == 2:
                try:
                    h1, m1 = [int(x) for x in w[0].split(":")]
                    h2, m2 = [int(x) for x in w[1].split(":")]
                    self._BRIEF_WINDOW = (h1, m1, h2, m2)
                except Exception:
                    pass
            if g:
                self._guardrails_override = g
                _log("jenny", "guardrails: active overrides %s" % sorted(g.keys(), key=str))
        except ImportError:
            pass
    
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
        """Forecast coordination needs. Context only — the LLM planner decides."""
        anticipations = []

        # Missing agents → surface as anticipation (planner may delegate a health check).
        presence = signals.get("presence", {})
        missing = [a for a in ["homelab", "finlay", "housekeep", "calendula", "connector"] if a not in presence]
        for agent in missing:
            key = f"missing:{agent}"
            if not self._is_handled(key, ttl_hours=6):
                anticipations.append({
                    "type": "preventive",
                    "content": f"Agent {agent} not reporting on bus — recommend a health-check delegation",
                    "action": "delegate_health_check",
                    "target": agent,
                    "dedup_key": key,
                })

        # Anticipate daily brief (context only), 15 min before window start.
        if self._in_brief_window(self._BRIEF_WINDOW, lead_min=15):
            anticipations.append({
                "type": "scheduled",
                "content": "05:00 org brief due soon",
                "action": "generate_brief",
            })

        return anticipations

    # ─── PLAN (LLM-determined within guardrails, deterministic fallback) ─────

    _DELEGATE_TARGETS = (
        "homelab", "baseplate", "vault", "courier", "inference",
        "finlay", "housekeep", "calendula", "connector",
    )
    _PLAN_ACTIONS = (
        "send_telegram", "coordinate_cross_agent", "delegate", "reply_chat",
        "initiate_onboarding", "generate_brief", "nothing",
    )
    _PLAN_COOLDOWN_MIN = {
        "send_telegram": 30, "delegate": 10, "coordinate_cross_agent": 15,
        "reply_chat": 5, "initiate_onboarding": 240,
    }
    _MAX_PLANS = 6
    # 05:00 org brief window (local). Guardrail override target via YAML.
    _BRIEF_WINDOW = (4, 50, 10)

    @staticmethod
    def _in_brief_window(window: tuple, now=None, lead_min: int = 0) -> bool:
        """True if `now` (datetime, default utcnow) falls inside the brief window.

        Handles both shapes:
          (h, start_min, end_min)      — brief window within hour `h`; if end_min
                                         < start_min it wraps into hour h+1
                                         (default (4,50,10) == 04:50-05:10).
          (h1, m1, h2, m2)             — full start-time / end-time override set
                                         from YAML brief_window: ["HH:MM","HH:MM"].
        lead_min shifts the window start earlier (used for "15 min before" cues).
        Windows are same-day minute-of-day ranges (start must not cross midnight).
        """
        if now is None:
            now = datetime.now()
        if len(window) == 4:
            h1, m1, h2, m2 = window
            start, end = h1 * 60 + m1, h2 * 60 + m2
        else:
            h, s_min, e_min = window
            start = h * 60 + s_min
            end = (h + 1) * 60 + e_min if e_min < s_min else h * 60 + e_min
        start -= lead_min
        cur = now.hour * 60 + now.minute
        return start <= cur <= end

    def _org_digest(self, signals: dict, insights: list, anticipations: list) -> str:
        lines = []
        ready = signals.get("ready_tasks", [])
        lines.append("ready_tasks=%d" % len(ready))
        for t in ready[:8]:
            lines.append("  - %s | %s | owner=%s" % (t.get("area", "?"), (t.get("title") or "?")[:60], t.get("owner", "?")))
        lines.append("overdue_tasks=%d" % len(signals.get("overdue_tasks", [])))
        missing = signals.get("presence", {})
        exp = ["homelab", "finlay", "housekeep", "calendula", "connector"]
        lines.append("missing_from_presence=%s" % [a for a in exp if a not in missing])
        return "\n".join(lines)

    def _llm_plan(self, signals: dict, insights: list, anticipations: list) -> list:
        """Ask the local LLM for the periodic plan. Returns raw plans or []."""
        import jenny_llm
        if not (jenny_llm.HOP.startswith("http") and jenny_llm.HOP_MODEL):
            return []
        try:
            digest = self._org_digest(signals, insights, anticipations)
            ins_lines = []
            for i, ins in enumerate(insights[:8]):
                ins_lines.append("  [%d] %s (severity=%s, suggests=%s)" % (
                    i, ins.get("content", "")[:120], ins.get("severity", "medium"),
                    ins.get("action_suggested", "?")))
            ins_txt = "\n".join(ins_lines) or "  (none)"
            ant_txt = "\n".join("  - %s (suggests=%s)" % (a.get("content", "")[:100], a.get("action")) for a in anticipations[:5]) or "  (none)"
            targets = ", ".join(self._DELEGATE_TARGETS)
            now = datetime.now()
            brief_ok = "yes" if self._in_brief_window(self._BRIEF_WINDOW, now) else "no"
            prompt = (
                "You are Jenny, Chief of Staff of a homelab agent team. Decide the minimal, safe action set for this periodic cycle.\n\n"
                f"Org overview:\n{digest}\n\n"
                "Fresh insights (only these are actionable):\n%s\n\n"
                "Forecasts (context only):\n%s\n\n" % (ins_txt, ant_txt) +
                "Available actions (ONLY these, strict JSON array):\n"
                '  {"action": "reply_chat", "content": "<short reply>", "ins_id": <int>}\n'
                '  {"action": "delegate", "target": "<one of: %s>", "content": "<task>", "ins_id": <int>}\n' % targets +
                '  {"action": "coordinate_cross_agent", "content": "<plan>", "ins_id": <int>}\n'
                '  {"action": "send_telegram", "content": "<escalation>", "ins_id": <int>}\n'
                '  {"action": "initiate_onboarding", "content": "<note>", "ins_id": <int>}\n'
                '  {"action": "generate_brief"}   — 05:00 org brief, only if now allows\n'
                '  {"action": "nothing"}\n'
                f"generate_brief allowed now: {brief_ok}\n"
                "Rules:\n"
                "- Every action EXCEPT nothing/generate_brief MUST carry ins_id of the insight it addresses.\n"
                "- reply_chat ONLY for genuine Rohit small-talk/greetings; otherwise delegate.\n"
                "- delegate target must be exactly one of the listed team members.\n"
                "- Never invent timelines or due dates.\n"
                "- Prefer 'nothing' when nothing urgent. Be conservative.\n"
                'Reply with ONLY valid JSON, a single array. No markdown fences.\n'
                'Example: [{"action": "delegate", "target": "homelab", "content": "restart unhealthy n8n", "ins_id": 0}]\n'
                'If nothing needs doing: [{"action": "nothing"}]'
            )
            text = jenny_llm.hop_ask(prompt, max_tokens=400)
            if not text:
                return []
            return self._parse_plans(text)
        except Exception as e:
            _log(self.name, "LLM plan error: %s" % e, "WARN")
            return []

    def _parse_plans(self, text: str) -> list:
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
                cleaned = re.sub(r"\n?```$", "", cleaned)
            data = json.loads(cleaned)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
        except Exception:
            pass
        try:
            m = re.search(r"\[.*\]", text, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                if isinstance(data, list):
                    return [d for d in data if isinstance(d, dict)]
        except Exception:
            pass
        return []

    def _validate_plan(self, plan: dict, signals: dict, insights: list) -> tuple:
        """Reject ungrounded, mis-targeted, or cooldown-violating plans."""
        action = str(plan.get("action", ""))
        if action not in self._PLAN_ACTIONS:
            return False, "'%s' not in allowlist" % action

        # nothing / generate_brief: no grounding required.
        if action == "nothing":
            return True, ""
        if action == "generate_brief":
            if not self._in_brief_window(self._BRIEF_WINDOW):
                return False, "generate_brief outside allowed window"
            return True, ""

        # Every other action must be grounded on a real, present insight.
        ins_id = plan.get("ins_id")
        if not isinstance(ins_id, int) or not (0 <= ins_id < len(insights)):
            return False, "%s: ins_id missing/out of range (ungrounded action)" % action
        ins = insights[ins_id]
        src_task = ins.get("source_task") or {}
        plan["source_task"] = src_task if isinstance(src_task, dict) and src_task else None
        if ins.get("dedup_key"):
            plan["dedup_key"] = ins["dedup_key"]
        plan["insight_content"] = ins.get("content", "")[:200]

        if action == "delegate":
            target = str(plan.get("target", "")).strip().lower()
            if target not in self._DELEGATE_TARGETS:
                return False, "delegate target '%s' not in roster" % target
            plan["target"] = target
            if not str(plan.get("content", "")).strip():
                return False, "delegate: empty task"

        elif action == "reply_chat":
            if ins.get("type") != "user_directive":
                return False, "reply_chat grounded on non-directive insight"

        elif action == "initiate_onboarding":
            if ins.get("type") != "onboarding_request":
                return False, "initiate_onboarding grounded on non-onboarding insight"

        # Cooldown guard (applied once the plan is otherwise valid).
        cooldowns = self.state.setdefault("plan_cooldowns", {})
        key = ":%s" % action if action != "delegate" else ":%s:%s" % (action, plan.get("target"))
        cd = cooldowns.get(key, 0)
        if time.time() < cd:
            return False, "%s: in cooldown" % action
        return True, ""

    def _apply_cooldown(self, action: str, target: str = ""):
        key = ":%s" % action if action != "delegate" else ":%s:%s" % (action, target)
        self.state.setdefault("plan_cooldowns", {})[key] = time.time() + self._PLAN_COOLDOWN_MIN.get(action, 10) * 60

    def plan(self, signals: dict, insights: list, anticipations: list) -> list:
        """Create coordination plans. LLM-first with deterministic fallback."""
        # Nothing to decide: no fresh insights and no scheduled work → no LLM call.
        if not insights and not anticipations:
            return []

        llm_plans = self._llm_plan(signals, insights, anticipations)
        if llm_plans:
            validated = []
            taken_actions = 0
            for p in llm_plans:
                if taken_actions >= self._MAX_PLANS:
                    break
                ok, why = self._validate_plan(p, signals, insights)
                if ok:
                    p["confidence"] = p.get("confidence", 0.75)
                    p["_llm"] = True
                    if p.get("action") not in ("nothing", "generate_brief"):
                        self._apply_cooldown(p["action"], p.get("target", ""))
                    validated.append(p)
                    taken_actions += 1
                else:
                    _log(self.name, "LLM plan REJECTED (%s): %s" % (p.get("action"), why), "WARN")
            if validated:
                _log(self.name, "LLM planned: " + ", ".join(str(v.get("action")) for v in validated))
                return validated
            _log(self.name, "LLM produced no valid plan — deterministic fallback", "WARN")
        else:
            _log(self.name, "LLM planner unavailable — deterministic fallback", "WARN")
        return self._fallback_plan(signals, insights, anticipations)

    def _fallback_plan(self, signals: dict, insights: list, anticipations: list) -> list:
        """Deterministic keyword planning (LLM offline / rejected output)."""
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
                # Agent name lives in dedup_key ("missing:<agent>"), not the last word.
                agent = ""
                dk = insight.get("dedup_key") or ""
                if dk.startswith("missing:"):
                    agent = dk.split(":", 1)[1]
                if agent not in self._DELEGATE_TARGETS:
                    agent = self._route_directive(insight.get("content", ""))
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
        
        # Daily brief at 5am (fallback when hop is down: fire when inside window)
        if self._in_brief_window(self._BRIEF_WINDOW):
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
                if action == "nothing":
                    results.append({"action": "nothing", "status": "ok"})
                    sent += 1

                elif action == "send_telegram":
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
                    if plan.get("_llm") and str(content).strip():
                        greeting = str(content)[:400]
                    else:
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

    def reflect(self, signals: dict, insights: list, plans: list, results: list) -> dict:
        reflection = super().reflect(signals, insights, plans, results)
        reflection["planner"] = {
            "cycle": self.cycle_count,
            "planned_by_llm": any(p.get("_llm", False) for p in plans),
            "actions": [r.get("action") for r in results],
            "skipped": [r.get("reason") for r in results if r.get("status") == "skipped"],
        }
        return reflection


if __name__ == "__main__":
    import sys
    agent = JennyAgent()
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        agent.run_daemon()
    else:
        print(json.dumps(agent.run_cycle(), indent=2))