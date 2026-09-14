#!/usr/bin/env python3
"""jenny_ops_review.py — Jenny's Officer's Review (proactive Chief-of-Staff).

Periodically gathers perception from every source, has the LLM "connect the
pieces" (Gmail items, homelab automation health, inference performance, open
board tasks), and turns the top findings into *initiatives* — structured,
deduped, actionable plans that become bus tasks/objectives for the team.

Stages:
  1. gather()   — pull signals: board/presence/objectives, journal, perf probe,
                  gmail scan. Each returns {"source", "text"} lines.
  2. synthesize(signals) — LLM produces up to N initiatives as STRICT JSON.
  3. act()      — dedupe against a seen-file, then:
                    * delegate the initiative's first step via bus task
                    * register an objective so progress is tracked
                    * send the digest to the coordination topic
  4. run_review() — orchestrates; returns the created initiatives (for logs).

Pure stdlib. Deterministic fallback if LLM offline (still surfaces board issues).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import jenny_llm

HERMES_HOME = Path(os.path.expanduser("~/.hermes"))
STATE_FILE = HERMES_HOME / "state" / "jenny_review_seen.json"
TOPIC = 10000

LLM_MAX = 50  # ~50k chars budget for LLM context


def _http_get(path: str) -> dict:
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:9107" + path, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def _load_write(mode):
    try:
        if mode == "r":
            return json.loads(STATE_FILE.read_text())
        return {"seen": {}}
    except Exception:
        return {"seen": {}}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _busy_task_lines(max: int = 14) -> list[str]:
    data = _http_get("/board")
    tasks = data.get("tasks", {}) if isinstance(data, dict) else {}
    lines = []
    for k, t in list(tasks.items())[:max]:
        if t.get("status") in ("ready", "pending"):
            lines.append("- [@%s] %s (pri %s)"
                         % (t.get("area", "?"), t.get("title", k), t.get("priority", "normal")))
    return lines


def _presence_lines() -> list[str]:
    data = _http_get("/status")
    pres = data.get("presence", {}) if isinstance(data, dict) else {}
    lines = []
    for agent, p in list(pres.items())[:14]:
        lines.append("- %s: %s (%s)" % (agent, p.get("kind", "?"), p.get("note", "")[:80]))
    return lines


def _journal_lines(n: int = 4) -> list[str]:
    jdir = HERMES_HOME / "collaborator-memory" / "journal"
    try:
        files = sorted(jdir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return []
    lines = []
    for f in files[:n]:
        try:
            head = f.read_text(errors="ignore")[:220]
        except Exception:
            continue
        lines.append("- %s: %s" % (f.name, " | ".join(head.splitlines()[:4])[:220]))
    return lines


def gather() -> dict:
    sig = {}
    sig["board"] = _busy_task_lines()
    sig["presence"] = _presence_lines()
    sig["journal"] = _journal_lines()
    try:
        import jenny_perf
        sig["perf"] = jenny_perf.probe()
    except Exception as e:
        sig["perf"] = {"level": "unknown", "detail": "probe failed: %s" % e}
    try:
        import jenny_gmail
        sig["gmail"] = jenny_gmail.scan()
    except Exception as e:
        sig["gmail"] = {"error": "gmail scan failed: %s" % e}
    return sig


def _render(sig: dict) -> str:
    out = []
    out.append("BOARD (pending/ready):")
    out.extend(sig.get("board") or ["  (none)"])
    out.append("PRESENCE:")
    out.extend(sig.get("presence") or ["  (none)"])
    out.append("INFERENCE HEALTH:")
    perf = sig.get("perf", {})
    out.append("  level=%s detail=%s" % (perf.get("level", "?"), perf.get("detail", "")))
    out.append("GMAIL:")
    g = sig.get("gmail", {})
    if isinstance(g, dict) and g.get("created"):
        out.extend("  - %s" % c.get("title") for c in g["created"])
    elif isinstance(g, dict) and g.get("error"):
        out.append("  %s" % g["error"])
    else:
        out.append("  (no new actionable items)")
    out.append("RECENT JOURNAL:")
    out.extend(sig.get("journal") or ["  (none)"])
    return "\n".join(out)


ROSTER = ["jenny", "homelab", "baseplate", "vault", "courier", "inference",
          "finlay", "housekeep", "calendula", "connector"]


def synthesize(sig: dict) -> list:
    """LLM: from the whole picture, name 1-3 initiatives. Strict JSON list."""
    ctx = _render(sig)[:LLM_MAX]
    prompt = """You are Jenny, Chief of Staff of a HOMELAB AGENT TEAM. These are
SOFTWARE agents that monitor a home server. IMPORTANT DOMAIN VOCABULARY:
- "board" = the agentbus TASK QUEUE (list of work items assigned to agents).
  It is NOT a physical circuit board. "pending"/"ready" are QUEUED TASKS.
- "presence" = each agent's heartbeat report (up/idle/working/done).
- "inference" = LLM serving performance (tokens/sec / latency).
- "gmail" = Rohit's inbox, already classified by you in a prior step.
- Each agent monitors a domain: baseplate=infra/deploy, housekeep=appliances,
  finlay=bills/finance, calendula=health/calendar, connector=contacts,
  courier=notifications, vault=memory/backup, inference=LLM serving,
  homelab=server diagnostics.

SITUATION FROM YOUR REVIEW:
%s

Find the 1-3 things that matter most across these sources — connecting the
pieces (e.g. a homelab degradation + a drained queue may mean one root cause; a
Gmail item may need a specialist). For each, propose an initiative.

Return STRICT JSON — a list:
[{"title": "short initiative title",
  "owner": "one of the roster agents exactly as listed",
  "first_step": "one concrete first action for that agent",
  "priority": "high|normal|low",
  "why": "one line citing the actual signal(s) from the situation above"}]

Rules:
- owner MUST be one of: %s. Pick the best fit; never invent agents.
- first_step must be concrete and actionable for that specific agent's domain.
- No trivial maintenance noise. Prioritize cross-source insight or anything
  degrading (inference latency > 5s, gateway unreachable, missing agents).
- If nothing is worth acting on, return [].
""" % (ctx, ", ".join(ROSTER))
    text = jenny_llm.hop_ask(prompt, max_tokens=500)
    parsed = _parse_json_list(text) if text else None
    if parsed:
        return _validate(parsed)
    return _fallback(sig)


def _validate(initiatives: list) -> list:
    """Drop initiatives with unknown owners or empty titles (LLM safety)."""
    out = []
    for ini in initiatives:
        owner = str(ini.get("owner", "")).strip().lower()
        title = str(ini.get("title", "")).strip()
        if owner not in ROSTER or not title:
            continue
        ini["owner"] = owner
        out.append(ini)
    return out


def _parse_json_list(text: str) -> list | None:
    import re
    text = (text or "").strip()
    fence = re.findall(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    if fence:
        text = fence[-1]
    start, end = text.find("["), text.rfind("]")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else ([data] if isinstance(data, dict) else None)
    except Exception:
        return None


def _fallback(sig: dict) -> list:
    """Deterministic fallback: surface failing health + busy criticals."""
    out = []
    perf = sig.get("perf", {})
    if perf.get("level") in ("critical", "degraded"):
        out.append({"title": "Inference gateway %s" % perf.get("level"),
                    "owner": "baseplate", "first_step": "Check hop gateway/provider health",
                    "priority": "high",
                    "why": perf.get("detail", "gateway performance regression")})
    if isinstance(sig.get("gmail"), dict) and sig["gmail"].get("created"):
        for c in sig["gmail"]["created"][:2]:
            out.append({"title": c.get("title", "gmail follow-up"),
                        "owner": c.get("agent_hint") or "jenny",
                        "first_step": "Handle: %s" % c.get("title", ""),
                        "priority": "normal",
                        "why": "new inbox item for Rohit"})
    return out


def _state():
    return _load_write("r")


def act(initiatives: list) -> list:
    if not initiatives:
        return []
    state = _state()
    seen = state.setdefault("seen", {})
    created = []
    for ini in initiatives[:3]:
        fingerprint = ini.get("title", "").strip().lower()
        if not fingerprint or fingerprint in seen:
            continue
        seen[fingerprint] = {"ts": datetime.now(timezone.utc).isoformat(),
                             "first_step": ini.get("first_step", "")}
        _delegate_initiative(ini)
        created.append(ini)
    # prune seen older than 7 days
    now = datetime.now(timezone.utc)
    state["seen"] = {k: v for k, v in seen.items()
                     if (now - datetime.fromisoformat(v.get("ts", now.isoformat()))).days < 7}
    _save_state(state)
    return created


def _delegate_initiative(ini: dict):
    import urllib.request
    owner = ini.get("owner") or "jenny"
    title = ini.get("title", "").strip()
    step = ini.get("first_step", title)[:200]
    payload = json.dumps({"op": "add", "area": owner, "title": step,
                          "owner": "jenny", "priority": ini.get("priority", "normal"),
                          "status": "ready",
                          "note": "initiative:%s | why=%s"
                                  % (title[:60], ini.get("why", "")[:120])}).encode()
    req = urllib.request.Request("http://127.0.0.1:9107/task", data=payload,
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass
    obj = json.dumps({"op": "add", "key": "init:%s" % title[:40], "title": title,
                      "desc": "why: %s" % ini.get("why", ""), "owner": "jenny",
                      "status": "open"}).encode()
    req2 = urllib.request.Request("http://127.0.0.1:9107/objectives", data=obj,
                                  method="POST", headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req2, timeout=5).read()
    except Exception:
        pass


def digest(created: list) -> str:
    if not created:
        return ""
    lines = ["🧭 *Officer's Review* — %d initiative(s)" % len(created)]
    for ini in created:
        lines.append("• *%s* → @%s" % (ini.get("title", "?"), ini.get("owner", "?")))
        lines.append("   step: %s" % ini.get("first_step", "")[:120])
        lines.append("   why: %s" % ini.get("why", "")[:120])
    return "\n".join(lines)


def send_digest(text: str) -> bool:
    if not text:
        return False
    import urllib.request
    payload = json.dumps({"text": text, "parse_mode": "Markdown",
                          "message_thread_id": TOPIC}).encode()
    req = urllib.request.Request("http://127.0.0.1:9198/telegram-send", data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
        return True
    except Exception as e:
        import autonomous_agent as aa
        return aa._send_telegram(text, TOPIC) if hasattr(aa, "_send_telegram") else False


def run_review() -> list:
    sig = gather()
    initiatives = synthesize(sig)
    created = act(initiatives)
    _ = send_digest(digest(created))
    return created


if __name__ == "__main__":
    print(json.dumps(run_review(), indent=2, default=str))