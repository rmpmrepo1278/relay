#!/usr/bin/env python3
"""
autonomous_agent.py — Base class for autonomous Hermes agents.

Each agent runs its own mind_loop cycle (OBSERVE → CONNECT → ANTICIPATE → PLAN → ACT → REFLECT → EVOLVE)
with domain-specific implementations. Agents share the Hermes infrastructure:
- narrative_memory (episodic + semantic)
- feedback_loop (outcome tracking + confidence calibration)
- autonomous_self (confidence calibration per action type)
- personal_model (life goals, work patterns, stress indicators)
- narrative_memory (episodic recall)
- agent_orchestrator (cross-agent coordination)
- n8n_bridge (Telegram communication)
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
from typing import Any, Dict, List, Optional, Callable
from abc import ABC, abstractmethod

# ─── Paths ──────────────────────────────────────────────────────────────────
HERMES_HOME = Path.home() / ".hermes"
STATE_DIR = HERMES_HOME / "state"
LOG_DIR = HERMES_HOME / "logs"
DATA_DIR = HERMES_HOME / "data"

STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ─── Shared imports ─────────────────────────────────────────────────────────
sys.path.insert(0, str(HERMES_HOME / "scripts"))

# Core Hermes modules (all optional - graceful degradation)
try:
    import narrative_memory as _narrative_memory
    _HAS_NARRATIVE = True
except ImportError:
    _HAS_NARRATIVE = False

try:
    import feedback_loop as _feedback_loop
    _HAS_FEEDBACK = True
except ImportError:
    _HAS_FEEDBACK = False

try:
    import autonomous_self as _autonomous_self
    _HAS_AUTONOMOUS_SELF = True
except ImportError:
    _HAS_AUTONOMOUS_SELF = False

try:
    import personal_model as _personal_model
    _HAS_PERSONAL_MODEL = True
except ImportError:
    _HAS_PERSONAL_MODEL = False

try:
    import insight_engine as _insight_engine
    _HAS_INSIGHT = True
except ImportError:
    _HAS_INSIGHT = False

try:
    from agent_orchestrator import dispatch_plan, decompose_plan, SPECIALISTS
    _HAS_ORCHESTRATOR = True
except ImportError:
    _HAS_ORCHESTRATOR = False

try:
    from n8n_bridge_server import _send_telegram_api, _topic_for_category, _md_escape
    _HAS_TELEGRAM = True
except ImportError:
    _HAS_TELEGRAM = False

# ─── Logging ────────────────────────────────────────────────────────────────
def _log(agent_name: str, msg: str, level: str = "INFO"):
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] {level} {agent_name}: {msg}"
    print(line)
    with open(LOG_DIR / f"{agent_name}.log", "a") as f:
        f.write(line + "\n")


# ─── Base Autonomous Agent ──────────────────────────────────────────────────
class AutonomousAgent(ABC):
    """
    Base class for autonomous Hermes agents.
    
    Each agent implements the 7-phase mind loop:
    OBSERVE → CONNECT → ANTICIPATE → PLAN → ACT → REFLECT → EVOLVE
    
    Agents run as daemons with configurable cycle intervals.
    """
    
    def __init__(
        self,
        name: str,
        domain: str,
        topic_id: int,
        cycle_interval_minutes: int = 30,
        tools: Optional[Dict[str, Callable]] = None,
    ):
        self.name = name
        self.domain = domain
        self.topic_id = topic_id
        self.cycle_interval = cycle_interval_minutes
        self.tools = tools or {}
        
        # State files
        self.state_file = STATE_DIR / f"{name}_state.json"
        self.memory_file = DATA_DIR / f"{name}_episodic.tsv"
        self.insights_file = DATA_DIR / f"{name}_insights.jsonl"
        
        # State
        self.state = self._load_state()
        self.cycle_count = self.state.get("cycle_count", 0)
        
        # Telegram
        self.telegram_chat_id = -1003976074764
        
        _log(name, f"Initialized autonomous agent: {name} (domain={domain}, topic={topic_id}, interval={cycle_interval_minutes}min)")
    
    def _load_state(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except Exception:
                pass
        return {
            "version": 1,
            "created": datetime.now(timezone.utc).isoformat(),
            "last_cycle": None,
            "cycle_count": 0,
            "goals": [],
            "insights": [],
            "patterns": [],
            "reflection_log": [],
            "action_history": [],
            "cross_agent_tasks": [],
        }
    
    def _save_state(self):
        self.state["last_cycle"] = datetime.now(timezone.utc).isoformat()
        self.state["cycle_count"] = self.cycle_count
        self.state_file.write_text(json.dumps(self.state, indent=2, default=str))
    
    # ─── Core mind loop phases ──────────────────────────────────────────────
    
    @abstractmethod
    def observe(self) -> dict:
        """OBSERVE: Gather domain-specific signals. Returns signals dict."""
        pass
    
    @abstractmethod
    def connect(self, signals: dict) -> List[dict]:
        """CONNECT: Find patterns, generate insights from signals. Returns insights list."""
        pass
    
    @abstractmethod
    def anticipate(self, signals: dict, insights: List[dict]) -> List[dict]:
        """ANTICIPATE: Predict needs, generate anticipatory actions. Returns anticipations list."""
        pass
    
    @abstractmethod
    def plan(self, signals: dict, insights: List[dict], anticipations: List[dict]) -> List[dict]:
        """PLAN: Create action plans. Returns plans list (each with action, priority, confidence)."""
        pass
    
    @abstractmethod
    def act(self, plans: List[dict], signals: dict) -> List[dict]:
        """ACT: Execute plans. Returns results list."""
        pass
    
    def reflect(self, signals: dict, insights: List[dict], plans: List[dict], results: List[dict]) -> dict:
        """REFLECT: What worked, what didn't, what did we learn?"""
        reflection = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle": self.cycle_count,
            "insights_generated": len(insights),
            "actions_planned": len(plans),
            "actions_executed": len(results),
            "errors": sum(1 for r in results if r.get("status") == "error"),
            "learnings": [],
        }
        
        # Track insight → action effectiveness
        for insight in insights:
            if insight.get("action_suggested") == "surface_to_telegram":
                reflection["learnings"].append(
                    f"Cross-domain insight surfaced: {insight['content'][:80]}"
                )
        
        # Track health trends
        for result in results:
            if result.get("status") == "error":
                reflection["learnings"].append(f"Action failed: {result.get('action', 'unknown')}")
        
        return reflection
    
    def evolve(self, reflection: dict):
        """EVOLVE: Update goals and strategies based on reflections."""
        # Add new goals from recurring patterns
        for learning in reflection.get("learnings", []):
            if "recurring" in learning.lower() or "pattern" in learning.lower():
                goal = {
                    "id": hashlib.md5(learning.encode()).hexdigest()[:8],
                    "title": f"Address: {learning[:60]}",
                    "created": datetime.now(timezone.utc).isoformat(),
                    "status": "active",
                    "source": "mind_loop_auto",
                }
                existing_titles = {g["title"] for g in self.state.get("goals", [])}
                if goal["title"] not in existing_titles:
                    self.state.setdefault("goals", []).append(goal)
                    _log(self.name, f"New goal created: {goal['title']}")
        
        # Prune completed/old goals
        self.state["goals"] = [
            g for g in self.state.get("goals", [])
            if g.get("status") == "active"
        ][:20]
        
        # Update personal model if available
        if _HAS_PERSONAL_MODEL:
            try:
                pm_state = _personal_model._load_state()
                goals = _personal_model.decay_and_reprioritise(pm_state)
                self.state["life_goals"] = goals
            except Exception:
                pass
    
    # ─── Telegram ────────────────────────────────────────────────────────────
    
    def send_telegram(self, text: str, thread_id: Optional[int] = None, parse_mode: str = "Markdown") -> bool:
        """Send message to Telegram via bridge."""
        if not _HAS_TELEGRAM:
            _log(self.name, "Telegram not available", "WARN")
            return False
        
        try:
            tid = thread_id or self.topic_id
            if parse_mode == "Markdown" and _HAS_TELEGRAM:
                try:
                    text = _md_escape(text)
                except Exception:
                    pass
            result = _send_telegram_api(
                self.telegram_chat_id,
                text,
                parse_mode=parse_mode,
                message_thread_id=tid
            )
            return result.get("ok", False)
        except Exception as e:
            _log(self.name, f"Telegram send error: {e}", "ERROR")
            return False
    
    def send_to_own_topic(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send to agent's own Telegram topic."""
        return self.send_telegram(text, thread_id=self.topic_id, parse_mode=parse_mode)
    
    # ─── Memory ──────────────────────────────────────────────────────────────
    
    def store_episode(self, event: dict):
        """Store episode in narrative memory."""
        if _HAS_NARRATIVE:
            try:
                _narrative_memory.store_episode(event)
            except Exception:
                pass
        # Also store locally
        self._append_local_memory(event)
    
    def _append_local_memory(self, event: dict):
        if not isinstance(event, dict) or "content" not in event:
            return
        ts = event.get("ts", datetime.now(timezone.utc).isoformat())
        etype = event.get("type", "generic")
        content = event.get("content", "")
        meta = json.dumps(event.get("metadata", {}), default=str)
        row = f"{ts}\t{etype}\t{content}\t{meta}\n"
        with open(self.memory_file, "a") as f:
            f.write(row)
    
    def retrieve_memory(self, query: str, k: int = 5) -> List[dict]:
        """Retrieve similar episodes from narrative memory."""
        if _HAS_NARRATIVE:
            try:
                return _narrative_memory.retrieve_similar(query, k=k)
            except Exception:
                pass
        return []
    
    # ─── Feedback & Confidence ──────────────────────────────────────────────
    
    def record_outcome(self, action: str, outcome: str, confidence: float = None):
        """Record action outcome for confidence calibration."""
        if _HAS_FEEDBACK:
            try:
                _feedback_loop.record_action(action, outcome)
            except Exception:
                pass
        if _HAS_AUTONOMOUS_SELF:
            try:
                _autonomous_self.record_action_outcome(action, outcome, confidence)
            except Exception:
                pass
    
    def get_confidence(self, action: str) -> float:
        """Get calibrated confidence for an action."""
        if _HAS_AUTONOMOUS_SELF:
            try:
                return _autonomous_self.get_confidence(action)
            except Exception:
                pass
        return 0.6
    
    # ─── Cross-agent coordination ────────────────────────────────────────────
    
    def delegate_to_agent(self, target_agent: str, task: str, priority: int = 5) -> dict:
        """Delegate a task to another agent.

        Orchestrator specialists (homelab, career_agent, ... ) are dispatched
        through the orchestrator. Any other target (roster members such as
        finlay/vault/courier, which run their own agent_loop daemon) is
        delegated as a bus task tagged area=<target> — that is the queue their
        `consume_assigned_tasks()` actually reads. Routing an arbitrary target
        through the orchestrator silently re-classified it to knowledge_miner,
        and the intended agent never saw the task.
        """
        if target_agent == self.name:
            return {"status": "self_delegation_skipped",
                    "detail": f"won't delegate to self ({target_agent})"}
        if _HAS_ORCHESTRATOR:
            if target_agent in SPECIALISTS or target_agent in ("infra", "career", "knowledge"):
                plan = {
                    "action": "add_task",
                    "content": task,
                    "goal_domain": target_agent,
                    "priority": priority,
                    "confidence": 0.7,
                }
                return dispatch_plan(plan)
            payload = json.dumps({"op": "add", "area": target_agent, "title": task,
                                  "owner": self.name, "priority": priority,
                                  "status": "ready"}).encode()
            try:
                import urllib.request
                req = urllib.request.Request("http://127.0.0.1:9107/task", data=payload,
                                             method="POST", headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    body = resp.read().decode() or "{}"
                    ok = bool(json.loads(body).get("ok", True))
                return {"status": "delegated" if ok else "error",
                        "route": f"bus_task:{target_agent}", "ok": ok}
            except Exception as e:
                return {"status": "error", "route": f"bus_task:{target_agent}", "error": str(e)}
        return {"status": "orchestrator_unavailable"}
    
    def publish_to_bus(self, channel: str, type_: str, text: str, data: dict = None) -> bool:
        """Publish event to agentbus."""
        try:
            import urllib.request, urllib.parse
            payload = {"channel": channel, "type": type_, "from": self.name, "text": text}
            if data:
                payload["data"] = data
            data_bytes = json.dumps(payload).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:9107/publish",
                data=data_bytes,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode()).get("ok", False)
        except Exception as e:
            _log(self.name, f"Bus publish error: {e}", "WARN")
            return False

    def report_presence(self, kind: str = "up", note: str = "") -> bool:
        """Publish agent presence heartbeat to agentbus."""
        try:
            import urllib.request
            payload = {"agent": self.name, "kind": kind, "note": note or f"{self.name} autonomous daemon"}
            data_bytes = json.dumps(payload).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:9107/presence",
                data=data_bytes,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode()).get("ok", False)
        except Exception as e:
            _log(self.name, f"Presence heartbeat error: {e}", "WARN")
            return False
    
    # ─── Main cycle ──────────────────────────────────────────────────────────
    
    def run_cycle(self) -> dict:
        """Run one complete mind loop cycle."""
        self.cycle_count += 1
        _log(self.name, f"Starting cycle #{self.cycle_count}")
        
        # Presence heartbeat
        self.report_presence()
        
        # 1. OBSERVE
        signals = self.observe()
        self.state["last_signals"] = signals
        
        # 2. CONNECT
        insights = self.connect(signals)
        self.state["insights"] = (self.state.get("insights", []) + insights)[-50:]
        for ins in insights:
            self.store_episode({"type": "insight", "content": ins.get("content", ""), "metadata": ins})
        
        # 3. ANTICIPATE
        anticipations = self.anticipate(signals, insights)
        
        # 4. PLAN
        plans = self.plan(signals, insights, anticipations)
        
        # 5. ACT
        results = self.act(plans, signals)
        self.state["action_history"] = (self.state.get("action_history", []) + results)[-100:]
        
        # 6. REFLECT
        reflection = self.reflect(signals, insights, plans, results)
        self.state["reflection_log"] = (self.state.get("reflection_log", []) + [reflection])[-50:]
        
        # 7. EVOLVE
        self.evolve(reflection)
        
        # Save state
        self._save_state()
        
        _log(self.name, f"Cycle #{self.cycle_count} complete: {len(insights)} insights, {len(plans)} plans, {len(results)} actions")
        
        return {
            "cycle": self.cycle_count,
            "signals": signals,
            "insights": insights,
            "anticipations": anticipations,
            "plans": plans,
            "results": results,
            "reflection": reflection,
        }
    
    def run_daemon(self):
        """Run the agent continuously as a daemon."""
        _log(self.name, f"Daemon starting. Interval: {self.cycle_interval} minutes")
        while True:
            try:
                self.run_cycle()
            except Exception as e:
                _log(self.name, f"Cycle error: {e}", "ERROR")
            time.sleep(self.cycle_interval * 60)
    
    def status(self) -> dict:
        """Return current agent status."""
        return {
            "name": self.name,
            "domain": self.domain,
            "topic_id": self.topic_id,
            "cycle_count": self.cycle_count,
            "last_cycle": self.state.get("last_cycle"),
            "active_goals": len(self.state.get("goals", [])),
            "total_insights": len(self.state.get("insights", [])),
            "total_actions": len(self.state.get("action_history", [])),
            "tools": list(self.tools.keys()),
        }


# ─── Tool registry ──────────────────────────────────────────────────────────

# Common tools available to all agents
COMMON_TOOLS = {
    "run_command": lambda cmd: _run_cmd(cmd),
    "send_telegram": lambda text, tid=None: _send_telegram(text, tid),
    "read_file": lambda path: Path(path).read_text() if Path(path).exists() else "",
    "write_file": lambda path, content: Path(path).write_text(content),
    "list_dir": lambda path: [str(p) for p in Path(path).iterdir()],
    "get_time": lambda: datetime.now(timezone.utc).isoformat(),
}

def _run_cmd(cmd: str, timeout: int = 30) -> dict:
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:500],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(e)}

def _send_telegram(text: str, thread_id: int = None) -> bool:
    """Send via centralized telegram_bridge with safety checks."""
    if not _HAS_TELEGRAM:
        return False
    try:
        from telegram_bridge import send_telegram
        tid = thread_id or -1003976074764
        result = send_telegram(text, thread_id=str(tid) if tid else None, parse_mode="Markdown")
        return result.get("status") in ("ok", "sent")
    except Exception as e:
        _log("autonomous_agent", f"Telegram send error: {e}", "ERROR")
        return False


if __name__ == "__main__":
    # Quick test
    print("Autonomous agent base class ready")
    print(f"Modules available: narrative={_HAS_NARRATIVE}, feedback={_HAS_FEEDBACK}, self={_HAS_AUTONOMOUS_SELF}, personal={_HAS_PERSONAL_MODEL}, insight={_HAS_INSIGHT}, orchestrator={_HAS_ORCHESTRATOR}, telegram={_HAS_TELEGRAM}")