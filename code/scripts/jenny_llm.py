#!/usr/bin/env python3
"""jenny_llm.py — LLM judgment core for Jenny (Chief of Staff, reaction mode).

Turns a raw user directive + org context into a structured intent that the
daemon executes:
  chat        -> Jenny replies herself
  execute     -> Jenny does it herself (run_command / send_telegram / bus)
  delegate    -> one specialist gets a bus task
  coordinate  -> decompose across multiple specialists, track each
  spawn       -> create a new specialized agent (safe template)
  retire      -> stop/disable an under-used agent

Uses the local hop gateway (haiku-4.5 -> poolside/laguna-s-2.1:free). If the
gateway is down, falls back to a deterministic keyword classifier so Jenny
never silently ignores Rohit.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

HOP = os.environ.get("HOP_URL", "http://127.0.0.1:8083/v1/chat/completions")
HOP_MODEL = os.environ.get("HOP_MODEL", "haiku-4.5")

TEAM = ["jenny", "homelab", "baseplate", "vault", "courier", "inference",
        "finlay", "housekeep", "calendula", "connector"]


# ── Fail-closed guardrail defaults (see guardrails.py) ──────────────────────
# An optional ~/.hermes/agents/guardrails.yaml [jenny_llm] section can add
# extra tools/intents (extra_tools / extra_intents) or raise the caps below.
ALLOWED_TOOLS = {"send_telegram", "create_bus_task", "run_command"}
ALLOWED_INTENTS = {"chat", "execute", "delegate", "coordinate", "spawn", "retire"}
MAX_DELEGATIONS = 3
MAX_STEPS = 5
MAX_REPLY = 600
MAX_ARGS = 300

try:
    from guardrails import load_guardrails
    _G = load_guardrails("jenny_llm")
    if _G.get("extra_tools"):
        ALLOWED_TOOLS |= set(_G["extra_tools"])
    if _G.get("extra_intents"):
        ALLOWED_INTENTS |= set(_G["extra_intents"])
    for _k in ("max_delegations", "max_steps", "max_reply", "max_args"):
        if _G.get(_k):
            globals()[_k.upper()] = _G[_k]
    if _G:
        try:
            os.makedirs(os.path.expanduser("~/.hermes/logs"), exist_ok=True)
            with open(os.path.expanduser("~/.hermes/logs/jenny_llm_guardrails.log"), "a") as _lf:
                _lf.write("%s guardrails overrides: %s\n" % (
                    __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                    sorted(_G.keys(), key=str)))
        except Exception:
            pass
except ImportError:
    pass


def hop_ask(prompt: str, max_tokens: int = 500) -> str | None:
    payload = {
        "model": HOP_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        req = urllib.request.Request(
            HOP, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.load(r)
        return data["choices"][0]["message"].get("content") or None
    except Exception:
        return None


# ─── Fallback deterministic classifier (LLM offline) ─────────────────────────

_DIRECT_VS_DELEGATE = [
    ("finlay", ["bill", "finance", "pay", "subscription", "budget", "expense", "invoice", "bank"]),
    ("calendula", ["calendar", "appointment", "medication", "doctor", "vaccine", "schedule", "health", "sleep"]),
    ("connector", ["birthday", "anniversary", "contact", "gift", "friend", "family", "people"]),
    ("housekeep", ["filter", "clean", "vacuum", "appliance", "clog", "air", "maintenance"]),
    ("baseplate", ["container", "docker", "deploy", "systemd", "uptime", "homelab", "infra", "server", "disk"]),
    ("vault", ["memory", "backup", "sync", "journal", "knowledge", "data", "store"]),
    ("courier", ["notify", "telegram", "digest", "topic", "broadcast", "remind"]),
    ("inference", ["model", "llm", "provider", "inference", "benchmark", "haiku", "laguna", "switchyard", "router", "decision router", "nvidia nemo", "nemo", "switch yard", "youtube", "youtu.be", "video", "applicability", "review video", "open source project"]),
]


def fallback_intent(directive: str) -> dict:
    # Fast path: if directive contains "fast"/"quick"/"asap", boost priority
    low_fast = directive.lower()
    is_fast = any(k in low_fast for k in ["fast","quick","asap","urgent","now"])
    low = directive.lower()
    # Typo tolerance
    low = low.replace("homelan", "homelab").replace("homenab", "homelab").replace("homelav", "homelab")
    # Use word boundaries for short greetings to avoid "hi" matching "this"
    import re
    if any(re.search(r"\b" + re.escape(t) + r"\b", low) for t in ["hi", "hey", "hello", "yo", "thanks", "thank you", "nice", "cool"] ) or any(t in low for t in ["how are you", "what's up", "whats up", "good job", "who are you", "jenny?"]):
        return {"intent": "chat",
                "reply": "Hey Rohit! Jenny here — I'm listening live. Give me a "
                         "task or ask anything, and I'll handle or delegate it."}
    # Prioritize homelab/baseplate when homelab/lab is mentioned, even if health also matches calendula
    low_has_homelab = any(k in low for k in ["homelab","homelan","baseplate","infra","server"])
    low_has_health = "health" in low
    best = None
    best_hits = 0
    for agent, keys in _DIRECT_VS_DELEGATE:
        hits = sum(1 for k in keys if k in low)
        # Boost homelab/baseplate when homelab context is present and health is also there
        if low_has_homelab and low_has_health and agent in ("homelab","baseplate"):
            hits += 2
        # Boost inference when switchyard/router present
        if any(k in low for k in ["switchyard","switch yard","decision router"]) and agent == "inference":
            hits += 3
        if hits > best_hits:
            best, best_hits = agent, hits
    if best:
        prio = "high" if is_fast else "normal"
        return {"intent": "delegate", "delegations": [{"agent": best, "priority": prio,
                                                       "task": directive}]}
    # Last resort: route to homelab ops (safe default), never raw shell on the directive.
    return {"intent": "delegate", "delegations": [{"agent": "homelab", "priority": is_fast and "high" or "normal",
                                                   "task": directive}]}


# ─── LLM intent parsing ──────────────────────────────────────────────────────

_ROSTER_STR = ", ".join(TEAM)


def _build_prompt(directive: str, board_snapshot: str) -> str:
    return f"""You are Jenny, Chief of Staff of a homelab agent team. You have
AUTHORITY over the team: you execute, delegate, coordinate, spawn new agents,
or retire unused ones. You coordinate when a task spans multiple agents.

Team roster: {_ROSTER_STR}
Current open-task board (area = which agent owns it):
{board_snapshot[:2000]}

User directive from Rohit: {directive}

Decide the single best action. Return STRICT JSON only, no markdown, no commentary:
{{
  "intent": "chat" | "execute" | "delegate" | "coordinate" | "spawn" | "retire",
  "reply": "short, warm confirmation for Rohit (1-2 lines)",
  "tools": [{{"tool": "run_command|send_telegram|create_bus_task", "args": "string"}}],
  "delegations": [{{"agent": "<from roster>", "task": "...", "priority": "high|normal|low"}}],
  "steps": [{{"agent": "<from roster>", "task": "..."}}],
  "spawn": {{"name": "<snake_case, max 20 chars>", "role": "one-line role", "triggers": ["..."]}},
  "retire": "<agent name from roster> | null"
}}

Rules:
- For greetings (hi/hello/hey/hola): give a brief, warm status snapshot (1-2 lines) using the board — e.g., "All 4 personal agents checked in, 2 bills due, lab healthy" — not generic "How can I help?"
- execute: only for things you can obviously do yourself (small commands/sends).
- delegate: one agent clearly owns this domain (bills->finlay, infra/homelab/health->baseplate/homelab (NOT calendula), health/schedule->calendula, llm/router/switchyard/model/provider->inference, youtube/video applicability->inference (analyze transcript)).
- coordinate: task needs 2+ agents; list ordered steps.
- spawn: ONLY if no existing agent owns the domain and it is a recurring need
  (e.g. a new data source to watch). Never spawn infra/core agents.
- CRITICAL: Never invent timelines, dates, or ETAs (e.g., "by EOD", "tomorrow", "next week") — if the board_snapshot contains no due date or timeline, you MUST say "No timeline set yet — tell me your deadline and I'll track it" instead of hallucinating one.
- Never invent timelines (e.g., "by EOD") — if no timeline is in board_snapshot, say "No timeline set yet" or ask Rohit.
- retire: ONLY if instructed explicitly by Rohit or an agent has been idle
  longer than anyone else with zero recent tasks. Be conservative.
- intent must be one of the exact strings listed.
"""


def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    fence = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence[-1]
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r'"intent"\s*:\s*"([^"]+)"', text)
        if m:
            return {"intent": m.group(1), "reply": "On it.", "raw": text[:400]}
        return None


def validate_intent(intent: dict | None) -> dict | None:
    """Guardrail pass over the LLM's structured intent.

    Binds every free-text vector: tools → allowlist, delegations/steps →
    roster-only targets, spawn/retire → name sanity. Unfixable intents are
    downgraded to 'chat' so Jenny never executes something unbounded.
    """
    if not isinstance(intent, dict):
        return None
    kind = intent.get("intent")
    if kind not in ALLOWED_INTENTS:
        return None

    # Tools: allowlist only, clamp args.
    tools = []
    for t in intent.get("tools", [])[:4]:
        if not isinstance(t, dict):
            continue
        tool = t.get("tool")
        if tool not in ALLOWED_TOOLS:
            continue
        tools.append({"tool": tool, "args": str(t.get("args", ""))[:MAX_ARGS]})
    intent["tools"] = tools

    # Delegations: roster-only targets, non-empty tasks, capped count.
    dels = []
    for d in intent.get("delegations", [])[:MAX_DELEGATIONS]:
        if not isinstance(d, dict):
            continue
        agent = str(d.get("agent", "")).strip().lower()
        task = str(d.get("task", "")).strip()
        if agent not in TEAM or not task:
            continue
        prio = str(d.get("priority", "normal"))
        if prio not in ("high", "normal", "low"):
            prio = "normal"
        dels.append({"agent": agent, "task": task[:400], "priority": prio})
    intent["delegations"] = dels

    # Steps: roster-only targets, capped count.
    steps = []
    for s in intent.get("steps", [])[:MAX_STEPS]:
        if not isinstance(s, dict):
            continue
        agent = str(s.get("agent", "")).strip().lower()
        task = str(s.get("task", "")).strip()
        if agent not in TEAM or not task:
            continue
        steps.append({"agent": agent, "task": task[:400]})
    intent["steps"] = steps

    # Spawn: name sanity only (agent_manager enforces the real rules).
    spawn = intent.get("spawn")
    if isinstance(spawn, dict):
        name = str(spawn.get("name") or "").strip().lower()
        if not re.match(r"^[a-z][a-z0-9_]{1,19}$", name):
            intent.pop("spawn", None)
            kind = "chat"  # invalid spawn name → don't run spawn
        else:
            role = str(spawn.get("role") or "")[:200].strip()
            triggers = [str(t)[:40].strip() for t in (spawn.get("triggers") or []) if str(t).strip()][:5]
            if not role:
                intent.pop("spawn", None)
                kind = "chat"
            else:
                intent["spawn"] = {"name": name, "role": role, "triggers": triggers}
    elif intent.get("spawn"):
        intent.pop("spawn", None)

    # Retire: roster-only; never spawn-empty.
    retire = str(intent.get("retire") or "").strip().lower()
    if retire:
        intent["retire"] = retire if retire in TEAM else None
    else:
        intent["retire"] = None

    # A non-chat intent that lost every actionable payload degrades to chat.
    if kind in ("delegate", "coordinate", "execute"):
        if kind == "delegate" and not intent["delegations"]:
            kind = "chat"
        elif kind == "coordinate" and not intent["steps"] and not intent["delegations"]:
            kind = "chat"
        elif kind == "execute" and not intent["tools"]:
            kind = "chat"

    intent["intent"] = kind
    intent["reply"] = str(intent.get("reply") or "On it.")[:MAX_REPLY]
    return intent


def decide(directive: str, board_snapshot: str = "") -> dict:
    """Return a structured intent. LLM first, deterministic fallback second."""
    prompt = _build_prompt(directive, board_snapshot)
    text = hop_ask(prompt, max_tokens=600)
    parsed = _parse_json(text) if text else None
    if parsed:
        parsed["raw_llm"] = bool(text)
        # Post-process: strip hallucinated EOD/tomorrow timelines if not in board
        reply = parsed.get("reply","")
        if any(k in reply.lower() for k in ["by eod","eod today","by tomorrow","by end of day"]) and "20" not in board_snapshot:
            # board_snapshot has no date, so hallucinated
            parsed["reply"] = reply.replace("by EOD today","no timeline set yet").replace("by EOD","no timeline set yet").replace("by tomorrow","no timeline set yet")
            if "no timeline" not in parsed["reply"].lower():
                parsed["reply"] = "No timeline set yet — tell me your deadline and I'll track it. " + parsed["reply"]
        parsed.setdefault("reply", "On it.")
        parsed.setdefault("tools", [])
        parsed.setdefault("delegations", [])
        parsed.setdefault("steps", [])
        return validate_intent(parsed) or fallback_intent(directive)
    return fallback_intent(directive)