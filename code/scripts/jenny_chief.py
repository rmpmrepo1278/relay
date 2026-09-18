#!/usr/bin/env python3
"""jenny_chief.py — Reactive Chief-of-Staff daemon.

Jenny stays always-on. Two brains:

1. REACTIVE (instant): an SSE listener on the agentbus `/stream` wakes Jenny the
   moment a directive appears (bridge /jenny, gmail bridge, or any task-add).
   `jenny_llm.decide()` gives a structured intent — chat / execute / delegate /
   coordinate / spawn / retire — and Jenny executes it immediately, then marks
   the source bus task done with proof.

2. PERIODIC (deterministic, inherited): the classic OBSERVE→PLAN→ACT cycle
   (journals, briefs, health checks) still runs every cycle_interval as a
   safety net and for proactive housekeeping.

If the hop gateway (LLM) is unreachable, jenny_llm falls back to keyword
routing, so Jenny never ignores Rohit.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from autonomous_agent import _log
from jenny_agent_autonomous import JennyAgent
import agent_manager
import jenny_llm

try:
    sys.path.insert(0, str(Path.home() / ".hermes" / "agents"))
    import agentscape
except Exception:
    agentscape = None

PRIO = {"high": 8, "normal": 5, "low": 3}


class JennyChief(JennyAgent):
    def __init__(self):
        super().__init__()
        self.reactive_wake = threading.Event()
        self.review_interval_hours = 6
        self.last_review = None

    # ─── context for the LLM ────────────────────────────────────────────────

    def _board_snapshot(self, max_tasks: int = 20) -> str:
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:9107/board", timeout=5) as r:
                tasks = json.loads(r.read().decode()).get("tasks", {})
        except Exception:
            return "(board unreachable)"
        lines = []
        for k, t in list(tasks.items())[:max_tasks]:
            lines.append("%s | %s | owner=%s | status=%s"
                         % (t.get("area", "?"), t.get("title", k),
                            t.get("owner", ""), t.get("status", "?")))
        return "\n".join(lines) or "(empty board)"

    # ─── REACTIVE cycle (instant, LLM-driven) ───────────────────────────────

    def _fresh_directives(self) -> list:
        signals = self.observe()
        ready = signals.get("ready_tasks", []) or []
        out = []
        for task in ready:
            if task.get("owner") in ("rohit", "user", "me") and task.get("area") == "jenny":
                key = "directive:%s" % task.get("key")
                if not self._is_handled(key):
                    out.append(task)
        return out[:3]

    def reactive_cycle(self) -> list:
        self.report_presence()
        directives = self._fresh_directives()
        if not directives:
            return []
        _log(self.name, "REACTIVE: %d fresh directive(s)" % len(directives))
        results = []
        for task in directives:
            title = task.get("title", "")
            key = task.get("key")
            try:
                intent = jenny_llm.decide(title, self._board_snapshot())
                outcome = self._execute_intent(intent, task)
            except Exception as e:
                _log(self.name, "REACTIVE LLM cycle failed, using fallback: %s" % e, "ERROR")
                fallback = jenny_llm.fallback_intent(title)
                try:
                    outcome = self._execute_intent(fallback, task)
                except Exception as e2:
                    _log(self.name, "REACTIVE fallback ALSO failed: %s" % e2, "ERROR")
                    # Do NOT mark handled and do NOT touch the board task: it stays
                    # ready, so the next SSE wake / periodic cycle retries it.
                    self.send_to_own_topic(
                        "⚠️ I couldn't process: %s — will retry." % title[:100])
                    continue
            self._mark_handled("directive:%s" % key)
            results.append(outcome)
            _log(self.name, "REACTIVE %s -> %s" % (title[:50], json.dumps(outcome)[:200]))
        return results

    def _execute_intent(self, intent: dict, task: dict) -> dict:
        kind = intent.get("intent")
        reply = intent.get("reply") or ""
        key = task.get("key")
        title = task.get("title", "")
        status = "ok"

        # Human-attention escalations (❓ prefix) are for Jenny to ACK,
        # never re-delegate — re-delegation would loop forever.
        if title.startswith("\u2753"):
            self.send_to_own_topic("Seen: %s" % title[:100])
            self._mark_task_ended(key, "done", "human-attention-acked")
            return {"kind": "chat", "status": "ok", "reply": "seen"}

        if kind == "chat":
            self.send_to_own_topic(reply or self._friendly_reply(task.get("title", "")))
            self._mark_task_ended(key, "done", "replied")
            return {"kind": "chat", "status": "ok", "reply": reply}

        if kind == "execute":
            n = 0
            for tool in intent.get("tools", [])[:4]:
                ok = self._run_tool(tool.get("tool"), tool.get("args", ""))
                status = "ok" if ok else "error"
                n += 1
            if reply:
                self.send_to_own_topic(reply)
            self._mark_task_ended(key, "done" if status == "ok" else "failed",
                                  "executed_self" if status == "ok" else "tool_error")
            return {"kind": "execute", "status": status, "reply": reply, "n_tools": n}

        if kind == "delegate":
            dls = intent.get("delegations", [])[:3]
            for d in dls:
                self.delegate_to_agent(d.get("agent"), d.get("task", ""),
                                       priority=PRIO.get(d.get("priority", "normal"), 5))
            names = ", ".join(d.get("agent", "?") for d in dls)
            self._mark_task_ended(key, "done", "delegated_to:%s" % names)
            self.send_to_own_topic(reply or "📤 Delegated to %s. I'll confirm results."
                                   % names)
            return {"kind": "delegate", "status": "ok", "to": names}

        if kind == "coordinate":
            steps = intent.get("steps", [])
            if not steps:
                return self._execute_intent({"intent": "delegate",
                                             "reply": reply,
                                             "delegations": intent.get("delegations", [])}, task)
            for step in steps[:5]:
                self.delegate_to_agent(step.get("agent"), step.get("task"),
                                       priority=PRIO.get(step.get("priority", "normal"), 5))
            plan = " → ".join("%s:%s" % (s.get("agent", "?"), s.get("task", "")[:30]) for s in steps)
            obj_title = task.get("title") or "coordinated task"
            self._create_objective(
                "coordinate:%s" % (key or datetime.now().strftime("%s")),
                obj_title, plan, owner="jenny")
            self._mark_task_ended(key, "done", "coordinated:%s" % plan)
            self.send_to_own_topic(reply or "🧩 Multi-agent plan queued: %s" % plan)
            return {"kind": "coordinate", "status": "ok", "plan": plan}

        if kind == "spawn":
            sp = intent.get("spawn") or {}
            name, role = (sp.get("name") or "").strip(), (sp.get("role") or "").strip()
            triggers = [t for t in (sp.get("triggers") or []) if (t or "").strip()]
            res = agent_manager.spawn_agent(name, role, triggers)
            msg = (reply + (" ✅ Agent %s live." % name) if res.get("ok")
                   else "⚠️ Couldn't spawn %s: %s" % (name, res.get("error")))
            self.send_to_own_topic(msg)
            self._mark_task_ended(key, "done" if res.get("ok") else "failed",
                                  "spawned:%s" % name if res.get("ok") else "spawn_error")
            return {"kind": "spawn", "status": "ok" if res.get("ok") else "error", **res}

        if kind == "retire":
            name = (intent.get("retire") or "").strip()
            res = agent_manager.retire_agent(name) if name else {"ok": False, "error": "no agent"}
            msg = (reply + (" ✅ %s retired & archived." % name) if res.get("ok")
                   else "⚠️ Can't retire %s: %s" % (name, res.get("error")))
            self.send_to_own_topic(msg)
            self._mark_task_ended(key, "done" if res.get("ok") else "failed", "retire:%s" % name)
            return {"kind": "retire", "status": "ok" if res.get("ok") else "error", **res}

        # unknown intent -> respond + close task
        self.send_to_own_topic(reply or self._friendly_reply(task.get("title", "")))
        self._mark_task_ended(key, "done", "handled:%s" % kind)
        return {"kind": kind or "unknown", "status": "ok"}

    # ─── bounded tools (dispatch targets — never arbitrary LLM shell) ────────

    # run_command is the one shell escape hatch; gate it to a read-only /
    # maintenance allowlist so the LLM can never pass arbitrary shell text.
    _ALLOWED_COMMAND_PREFIXES = (
        "systemctl --user status", "systemctl --user is-active", "systemctl --user is-failed",
        "systemctl --user list-units", "ps aux", "free -h", "df -h",
        "docker ps", "docker stats --no-stream", "docker images",
        "kopia snapshot list", "kopia repository status",
        "journalctl --user", "cat /proc/loadavg",
        "uptime", "date", "whoami", "hostname",
    )
    _SHELL_BAD = re.compile(r"[;&|`]|\$\(|>\s|\brm\s+|\bmkfs|\bdd\b|\bshutdown|\breboot|\bsudo\s+rm")

    def _run_tool(self, tool: str, args: str) -> bool:
        try:
            _r = False
            if tool == "send_telegram":
                _r = self.send_to_own_topic(str(args)[:2000])
                _out = "sent"
            elif tool == "create_bus_task":
                self.create_bus_task("jenny-span", str(args), owner="jenny")
                _r = True
                _out = "added"
            elif tool == "run_command":
                cmd = str(args).strip()
                if _log and self._SHELL_BAD.search(cmd):
                    _log(self.name, "run_command REJECTED (unsafe pattern): %s" % cmd[:120], "WARN")
                    _r, _out = False, "blocked"
                else:
                    allowed = any(cmd.startswith(p) for p in self._ALLOWED_COMMAND_PREFIXES)
                    if not allowed:
                        _log(self.name, "run_command REJECTED (not in allowlist): %s" % cmd[:120], "WARN")
                        _r, _out = False, "blocked"
                    else:
                        from autonomous_agent import _run_cmd
                        res = _run_cmd(cmd, timeout=30)
                        _r, _out = bool(res.get("ok")), ("success" if res.get("ok") else "failed")
            try:
                if agentscape:
                    agentscape.record("jenny_chief", tool, str(args)[:200], outcome=_out,
                                      target="", evidence="", risk=(tool in ("run_command", "create_bus_task")))
            except Exception:
                pass
            return _r
        except Exception as e:
            _log(self.name, "tool %s failed: %s" % (tool, e), "ERROR")
            return False

    def create_bus_task(self, area: str, title_: str, owner: str = "jenny",
                        priority: int = 5, status: str = "ready"):
        import urllib.request
        payload = json.dumps({"op": "add", "area": area, "title": title_,
                              "owner": owner, "priority": priority,
                              "status": status}).encode()
        req = urllib.request.Request("http://127.0.0.1:9107/task", data=payload,
                                     method="POST", headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=4).read()
            return True
        except Exception:
            return False

    def _create_objective(self, key: str, title_: str, desc: str, owner: str):
        import urllib.request
        payload = json.dumps({"op": "add", "key": key, "title": title_,
                              "desc": desc, "owner": owner,
                              "status": "open"}).encode()
        req = urllib.request.Request("http://127.0.0.1:9107/objectives", data=payload,
                                     method="POST", headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=4).read()
        except Exception:
            pass

    # ─── SSE wake watcher ────────────────────────────────────────────────────

    def _sse_watcher(self):
        import http.client
        while not self._shutdown.is_set():
            try:
                conn = http.client.HTTPConnection("127.0.0.1", 9107, timeout=60)
                conn.request("GET", "/stream")
                resp = conn.getresponse()
                while True:
                    line = resp.readline()
                    if not line:
                        break
                    line = line.decode().strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        ev = json.loads(line[5:])
                    except Exception:
                        continue
                    channel = ev.get("channel", "")
                    etype = ev.get("type", "")
                    if channel == "board" and etype == "task-add":
                        self.reactive_wake.set()
                    elif channel in ("jenny", "coordination"):
                        self.reactive_wake.set()
            except Exception as e:
                _log(self.name, "SSE watcher: %s" % e, "ERROR")
            time.sleep(2)

    # ─── PROACTIVE review (Chief-of-Staff, non-instruction driven) ──────────

    def proactive_review(self):
        """Periodic Officer's Review: pull signal sources, let the LLM connect
        the pieces and surface initiatives. See jenny_ops_review.py."""
        try:
            import jenny_ops_review
            self.last_review = datetime.now(timezone.utc).isoformat()
            return jenny_ops_review.run_review()
        except ModuleNotFoundError:
            return []
        except Exception as e:
            _log(self.name, "ops review failed: %s" % e, "ERROR")
            return []

    # ─── daemon main loop ────────────────────────────────────────────────────

    def run_chief_daemon(self):
        self._shutdown = threading.Event()
        thread = threading.Thread(target=self._sse_watcher, daemon=True)
        thread.start()
        last_review = None
        next_full = 0.0
        _log(self.name, "Chief daemon online: reactive (SSE) + periodic (%sm)" % self.cycle_interval)
        while True:
            try:
                if self.reactive_wake.is_set():
                    self.reactive_wake.clear()
                    try:
                        self.reactive_cycle()
                    except Exception as e:
                        _log(self.name, "reactive cycle error: %s" % e, "ERROR")
                now = time.time()
                if now >= next_full:
                    next_full = now + self.cycle_interval * 60
                    self.run_cycle()
                if (last_review is None or
                        (datetime.now(timezone.utc) - datetime.fromisoformat(last_review)).total_seconds()
                        >= self.review_interval_hours * 3600):
                    last_review = datetime.now(timezone.utc).isoformat()
                    try:
                        self.proactive_review()
                    except Exception as e:
                        _log(self.name, "proactive_review: %s" % e, "ERROR")
            except Exception as e:
                _log(self.name, "daemon cycle error: %s" % e, "ERROR")
            time.sleep(3)


if __name__ == "__main__":
    agent = JennyChief()
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        agent.run_chief_daemon()
    else:
        print(json.dumps(agent.run_cycle(), indent=2))