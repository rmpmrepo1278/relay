#!/usr/bin/env python3
"""heavy_dispatcher.py — dispatcher for the full-Hermes "heavy lifter".

Polls agentbus for tasks owned by `hermes-heavy` and runs them through the
one-shot Hermes core (`hermes -z`) with a STRUCTURAL fail-closed toolset gate
(web, search, file, skills only — no terminal/execute_code/browser/delegation/
cronjob in the schema, ever). Every job:

  1. ready      → dispatcher posts a human-approval proposal to the personal
                  topic (10122) and marks the task awaiting.
  2. awaiting   → human runs `/heavy approve <id>` / `/heavy deny <id>` via the
                  bridge (or the task times out after HEAVY_APPROVE_MINUTES).
  3. approved   → dispatcher runs the one-shot core (timeout, usage report,
                  per-job scratch workdir), writes `result`+`proof` back,
                  records spend in the daily budget, and marks done/failed.

All decisions + spend land in the unified agentscape ledger.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
SCRIPTS = HERMES_HOME / "scripts"
DATA = HERMES_HOME / "data"

BUS = os.environ.get("AGENTBUS_URL", "http://127.0.0.1:9107")
BRIDGE = os.environ.get("BRIDGE_URL", "http://127.0.0.1:9199")
PERSONAL_TOPIC = int(os.environ.get("HEAVY_APPROVE_TOPIC", "10122"))

RUNTIME = os.environ.get("HEAVY_RUNTIME",
                         str(Path.home() / ".hermes" / "hermes-runtime" / ".venv" / "bin" / "python"))
REPO = os.environ.get("HEAVY_REPO", str(Path.home() / ".hermes" / "hermes-agent"))
TOOLSETS = os.environ.get("HEAVY_TOOLSETS", "web,search,file,skills")

STATE_FILE = DATA / "heavy_state.json"
BUDGET_FILE = DATA / "heavy_budget.json"
LEDGER = DATA / "decision_ledger.jsonl"

try:
    sys.path.insert(0, str(HERMES_HOME / "agents"))
    import agentscape
except Exception:
    agentscape = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _bus(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BUS + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _tg(text):
    payload = {"text": text, "parse_mode": "", "priority": "normal",
               "message_thread_id": PERSONAL_TOPIC}
    req = urllib.request.Request(BRIDGE + "/telegram-send", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── state / budget ─────────────────────────────────────────────────────────

def _load(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _budget():
    b = _load(BUDGET_FILE, {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if b.get("date") != today:
        b = {"date": today, "tokens": 0, "usd": 0.0}
    return b


def _spend(usage):
    b = _budget()
    b["tokens"] = b.get("tokens", 0) + int(usage.get("total_tokens", 0))
    b["usd"] = b.get("usd", 0.0) + float(usage.get("estimated_cost_usd", 0) or 0)
    _save(BUDGET_FILE, b)
    return b


def _record(actor, action, rationale, outcome="unknown", target="", evidence="", risk=False, params=None):
    if agentscape:
        try:
            agentscape.record(actor, action, rationale, outcome=outcome,
                              target=target, evidence=(evidence or "")[:400], risk=risk, params=params or {})
        except Exception:
            pass


# ── lifecycle ──────────────────────────────────────────────────────────────

def _all_tasks():
    r = _bus("GET", "/board")
    return r.get("tasks", {}) if r.get("ok") else {}


def _set(key, **fields):
    return _bus("POST", "/task", {"op": "set", "key": key, **fields})


def _propose(task_id, task):
    title = task.get("title", task_id)
    note = str(task.get("note", ""))[:400]
    msg = (
        f"🔬 *Heavy task proposal* `{task_id}`\n"
        f"{title}\n"
        + (f"```\n{note}\n```\n" if note else "\n")
        + f"Approve: `/heavy approve {task_id}`\nDeny: `/heavy deny {task_id}`"
    )
    _tg(msg)
    _set(task_id, status="awaiting", proof=f"proposal sent {_now()}")
    _record("hermes-heavy", "proposal", f"{title}", outcome="awaiting",
            target=task_id, params={"kind": "heavy", "approve": f"/heavy approve {task_id}"})


def _run_job(task_id, task):
    title = task.get("title", task_id)
    note = str(task.get("note", "")).strip()
    prompt = note if note else title
    if len(prompt) > 4000:
        prompt = prompt[:4000] + "\n(truncated)"
    scratch = HERMES_HOME / "heavy" / task_id
    scratch.mkdir(parents=True, exist_ok=True)
    usage = DATA / f"heavy_{task_id}.usage.json"

    env = dict(os.environ)
    env["HERMES_HOME"] = str(HERMES_HOME)
    env["PYTHONPATH"] = str(REPO)
    cmd = [RUNTIME, "-m", "hermes_cli.main", "-z", prompt, "-t", TOOLSETS,
           "--usage-file", str(usage)]
    try:
        proc = subprocess.run(cmd, cwd=str(scratch), env=env, capture_output=True,
                              text=True, timeout=int(os.environ.get("HEAVY_TIMEOUT", "1200")))
        out = (proc.stdout or "").strip()
        ok = proc.returncode == 0
        reason = "completed" if ok else f"exit {proc.returncode}"
    except subprocess.TimeoutExpired:
        ok, out, reason = False, "", "timed out"
        _set(task_id, status="failed", proof=f"timed out", result="heavy job timed out")
    except Exception as e:
        ok, out, reason = False, "", f"dispatch error: {e}"
        _set(task_id, status="failed", proof=str(e)[:200], result="dispatch error")

    usage_data = _load(usage, {})
    b = _spend(usage_data)
    summary = f"tokens={usage_data.get('total_tokens', 0)} ${usage_data.get('estimated_cost_usd', 0)} " \
              f"calls={usage_data.get('api_calls', 0)} model={usage_data.get('model', '?')}"
    result = (out[:290] if out else reason)
    _set(task_id, status=("done" if ok else "failed"), proof=summary, result=result)
    _record("hermes-heavy", "dispatch", title, outcome=("success" if ok else "failed"),
            target=task_id, evidence=summary, params={"usage": usage_data, "reason": reason,
                                                       "budget_day": b.get("date")})
    _tg((f"✅ *Heavy done* `{task_id}` — {summary}\n```\n{result[:200]}\n```"
         if ok else f"❌ *Heavy failed* `{task_id}` — {reason} ({summary})"))
    return ok


def _tick(state, budget):
    daily_cap = int(os.environ.get("HEAVY_DAILY_TOKEN_BUDGET", "500000"))
    tasks = _all_tasks()
    now = datetime.now(timezone.utc)
    heavy = {k: t for k, t in tasks.items() if t.get("owner") == "hermes-heavy"}
    for tid, t in sorted(heavy.items()):
        st = t.get("status")
        title = t.get("title", tid)
        if st == "ready":
            dup = state.get("last_run")
            if dup and title == dup.get("title") and (now - datetime.fromisoformat(dup.get("at", _now()))).total_seconds() < 6 * 3600:
                _set(tid, status="failed", proof="duplicate title within 6h", result="dedup")
                continue
            _propose(tid, t)
            state["proposals"][tid] = now.isoformat()
        elif st == "awaiting":
            proposed = state.get("proposals", {}).get(tid)
            if proposed and (now - datetime.fromisoformat(proposed)).total_seconds() > int(os.environ.get("HEAVY_APPROVE_MINUTES", "30")) * 60:
                _set(tid, status="cancelled", proof="approval timeout", result="")
                _record("hermes-heavy", "approval_timeout", title, outcome="cancelled", target=tid)
                _tg(f"⏰ *Heavy proposal expired* `{tid}` — no approval in time.")
        elif st == "approved":
            if budget.get("tokens", 0) >= daily_cap:
                _set(tid, status="failed", proof=f"daily token budget exceeded ({budget['tokens']})", result="budget")
                _record("hermes-heavy", "budget_refused", title, outcome="failed", target=tid,
                        evidence=f"budget={budget['tokens']}/{daily_cap}")
                _tg(f"🚫 Heavy job `{tid}` refused: daily token budget exceeded "
                    f"({budget['tokens']}/{daily_cap}).")
                continue
            _set(tid, status="running", proof=f"started {_now()}")
            _record("hermes-heavy", "dispatch_start", title, outcome="running", target=tid)
            ok = _run_job(tid, t)
            state["last_run"] = {"title": title, "at": now.isoformat()}
            state["failures"][tid] = state.get("failures", {}).get(tid, 0) + (0 if ok else 1)
    _save(STATE_FILE, state)


def main():
    once = "--once" in sys.argv or "-1" in sys.argv
    _log(f"heavy-dispatcher up: toolsets=[{TOOLSETS}] runtime={RUNTIME} topic={PERSONAL_TOPIC}")
    state = _load(STATE_FILE, {"proposals": {}, "failures": {}, "last_run": None})
    while True:
        try:
            budget = _budget()
            _tick(state, budget)
        except Exception as e:
            _log(f"tick error: {e}")
        if once:
            _log("--once: single pass complete")
            break
        time.sleep(int(os.environ.get("HEAVY_POLL", "30")))


if __name__ == "__main__":
    main()