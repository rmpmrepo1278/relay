#!/usr/bin/env python3
"""agent_loop.py — Shared autonomous agent loop frame (Hermes-style).

Turns a deterministic domain script into a persistent, reflective,
self-learning agent process. Each domain agent (baseplate, vault, courier,
inference, finlay, housekeep, calendula, connector) runs this loop:

  loop (default ~300s interval, configurable):
    1. read playbook priorities (memory/<name>.md)
    2. load memory namespace (store.json + reflection journal)
    3. heartbeat presence on agentbus
    4. decide action: if hop gateway reachable (offline-safe fallback),
       ask local LLM what to check based on playbook + recent history;
       else fall back to deterministic 'check' command
    5. execute the decision (domain script subcommand) as a tool
    6. capture outcome, benchmark/proof
    7. reflect: append to reflection journal, update store meta,
       optionally write playbook learning (when LLM available)
    8. post board task for anything requiring human attention

Offline behavior: if AGENTBUS or the hop gateway is unreachable, the agent
still runs its deterministic check (domain script) and logs locally; nothing
requires internet. Coordination state is republished once the bus returns.

Designed to run under systemd --user as:
  systemd unit: agent-<name>.service  ExecStart=/usr/bin/python3 .../agent_loop.py <name>
"""
import sys, os, json, datetime, subprocess, time, urllib.request, urllib.error, shlex, signal

# ─────────────────────────────────────────────────────────────────────
NAME = sys.argv[1] if len(sys.argv) > 1 else None
if not NAME:
    sys.exit("usage: agent_loop.py <agent_name> [--once] [--interval SECONDS]")

HERE = os.path.dirname(os.path.abspath(__file__))
HERMES_HOME = os.path.expanduser("~/.hermes")
AGENT_DIR = os.path.join(HERMES_HOME, "agents")
DOMAIN_SCRIPT = os.path.join(AGENT_DIR, NAME + ".py")
STORE = os.path.join(AGENT_DIR, NAME, "store.json")
REFLECT = os.path.join(AGENT_DIR, NAME, "reflection.jsonl")
PLAYBOOK_CANDIDATES = [
    os.path.join(HERMES_HOME, "agentbus", "memory", NAME + ".md"),
    os.path.join(HERMES_HOME, "collaborator-memory", "memory", NAME + ".md"),
]
PLAYBOOK = PLAYBOOK_CANDIDATES[0]
BUS = os.environ.get("AGENTBUS_URL", "http://127.0.0.1:9107")
HOP = os.environ.get("HOP_URL", "http://127.0.0.1:8083/v1/chat/completions")
HOP_MODEL = os.environ.get("HOP_MODEL", "haiku-4.5")

DEFAULT_INTERVAL = 300  # seconds between autonomous cycles
STOP_REQUESTED = False


def log(msg, level="INFO"):
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"[{ts}] [{level}] [{NAME}] {msg}"
    print(line, flush=True)
    try:
        with open(os.path.join(AGENT_DIR, "logs", NAME + "-loop.log"), "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def bus(path, method="GET", payload=None, timeout=6):
    url = BUS + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def hop_ask(prompt, max_tokens=300):
    """Ask the local hop gateway (haiku-4.5 → magnitude local). Returns text or None."""
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
    except Exception as e:
        return None


def load_store():
    try:
        with open(STORE) as f:
            return json.load(f)
    except Exception:
        return {"items": [], "meta": {}}


def save_store(data):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, STORE)



def load_personality():
    """Load personality Identity/Voice/Traits for prompt injection and evolution."""
    for cand in PLAYBOOK_CANDIDATES:
        try:
            with open(cand) as f:
                txt=f.read()
                # Extract Identity + Voice & Tone + Core Traits (first 800 chars of personality)
                if "## Identity" in txt:
                    start=txt.find("## Identity")
                    # Take up to Evolution Log
                    end=txt.find("## Evolution Log", start)
                    snippet=txt[start:end if end!=-1 else start+800]
                    return snippet[:800]
                return txt[:800]
        except: continue
    return ""

def record_evolution(note):
    """Append a line to the agent's personality Evolution Log."""
    for cand in PLAYBOOK_CANDIDATES:
        if os.path.exists(cand):
            try:
                txt=open(cand).read()
                if "## Evolution Log" in txt:
                    # Append under Evolution Log
                    txt=txt.rstrip()+"\n- "+note+"\n"
                    open(cand,"w").write(txt)
                    return True
            except: pass
    return False

def playbook_lines():
    try:
        with open(PLAYBOOK) as f:
            return f.read()
    except OSError:
        return ""


def append_reflection(entry):
    os.makedirs(os.path.dirname(REFLECT), exist_ok=True)
    entry["ts"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry["agent"] = NAME
    with open(REFLECT, "a") as f:
        f.write(json.dumps(entry) + "\n")


def execute_domain(cmd_args, timeout=240):
    """Run the domain script as a tool. Returns (rc, output)."""
    try:
        proc = subprocess.run(
            [sys.executable, DOMAIN_SCRIPT] + cmd_args,
            capture_output=True, text=True, timeout=timeout,
            cwd=AGENT_DIR)
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out[-2000:]
    except Exception as e:
        return None, str(e)


def decide_action():
    """LLM decides what the agent should do this cycle based on playbook + history."""
    store = load_store()
    last = store.get("meta", {}).get("last_action") or "none yet"
    pb = playbook_lines()[:1500]
    personality = load_personality()[:600]
    prompt = (
        f"You are the autonomous '{NAME}' homelab agent. Your personality:\n{personality}\n\nYour playbook priorities:\n"
        f"{pb}\n\n"
        f"Your store summary (first 800 chars):\n{json.dumps(store)[:800]}\n\n"
        f"Last action: {last}\n\n"
        f"Decide the single most useful action for this cycle. Respond with exactly one line:\n"
        f"ACTION <subcommand_and_args> | REASON <one sentence>\n"
        f"Example: ACTION check | REASON scheduled health sweep\n"
        f"Allowed actions: check, report, or a specific subcommand the domain script supports."
    )
    text = hop_ask(prompt)
    if not text:
        return "check", "hop gateway offline — deterministic fallback"
    for line in text.splitlines():
        for line in text.splitlines():
            ls = line.strip()
            if ls.upper().startswith("ACTION"):
                rest = ls[len("ACTION"):].strip().strip("*: —-")
                if "|" in rest:
                    action, reason = rest.split("|", 1)
                else:
                    action, reason = rest, ""
                action = action.strip()
                if not action:
                    continue
                parts = shlex.split(action)
                return parts, reason.strip()
        lowered = text.lower()
        for candidate in ("check", "report"):
            if candidate in lowered:
                return [candidate], "parsed from free-text LLM reply"
        return "check", "malformed LLM decision — fallback"


def consume_assigned_tasks(max_tasks=2):
    """Claim + execute bus tasks delegated to this agent (area == NAME).

    Jenny / the orchestrator / the bridge enqueue tasks via POST /task with
    area=<agent>. The title is treated as domain-script args (e.g. "check",
    "report", "add ...", "send ..."). Returns list of completed task dicts.

    Only tasks assigned BY SOMEONE ELSE are consumed — tasks the domain script
    itself posts for human attention (owner == this agent) are left alone.
    """
    board = bus("/board", method="GET")
    tasks = board.get("tasks", {}) if isinstance(board, dict) else {}
    mine = [{"key": k, **v} for k, v in tasks.items()
            if v.get("area") == NAME
            and v.get("status") in ("pending", "ready")
            and v.get("owner", "") not in ("", NAME)]
    mine.sort(key=lambda t: t.get("priority", "normal"))
    done = []
    for t in mine[:max_tasks]:
        key = t["key"]
        title = (t.get("title") or "check").strip()
        claim = bus("/task", method="POST", payload={"op": "set", "key": key,
                                                     "status": "in_progress", "owner": NAME})
        ok_claim = bool(claim.get("ok", True))
        try:
            args = shlex.split(title)
            if not args:
                args = ["check"]
        except Exception:
            args = ["check"]
        log(f"consuming assigned task [{key}] {title}")
        rc, out = execute_domain(args, timeout=300)
        proof = out[-500:]
        final = "done" if rc == 0 else "failed"
        bus("/task", method="POST", payload={"op": "set", "key": key,
                                             "status": final, "owner": NAME, "proof": proof})
        append_reflection({"action": ["bus_task:" + key] + args, "reason": f"delegated task '{title}'",
                           "rc": rc, "output_tail": proof, "claimed": ok_claim})
        done.append({"key": key, "status": final, "rc": rc})
    if done:
        log(f"consumed {len(done)} assigned task(s): " + ", ".join(f"{d['key']}={d['status']}" for d in done))
    return done


def cycle():
    """One autonomous cycle."""
    store = load_store()
    now = datetime.datetime.now(datetime.timezone.utc)

    # presence heartbeat
    bus("/presence", method="POST", payload={
        "agent": NAME, "kind": "working", "note": "autonomous loop cycle"})

    # consume any delegated bus tasks first (claimed work supersedes open-ended decide)
    tasks_done = consume_assigned_tasks(max_tasks=2)

    # decide + execute
    action, reason = decide_action()
    if isinstance(action, str):
        action = [action]
    if tasks_done:
        reason = f"completed {len(tasks_done)} delegated task(s); " + reason
    log(f"decided: {action} ({reason})")
    rc, out = execute_domain(action, timeout=300)
    log(f"executed {action}: rc={rc}")

    # reflection entry
    # Evolution: progressive improvement tracking
    meta = store.setdefault("meta", {})
    perf = meta.setdefault("performance", {})
    perf["cycles"] = perf.get("cycles",0)+1
    perf["last_rc"] = rc
    if rc==0:
        perf["success_streak"] = perf.get("success_streak",0)+1
    else:
        perf["success_streak"] = 0
    # Every 20 cycles, ask LLM for a personality tweak (evolve)
    if perf["cycles"] % 20 == 0:
        evo_prompt = f"You are {NAME}. Review your last 3 reflections and suggest ONE sentence to add to your Evolution Log that makes you better at your focus area. Be specific and personality-consistent."
        evo = hop_ask(evo_prompt, max_tokens=80)
        if evo and len(evo.strip())>20:
            record_evolution(f"{datetime.datetime.now().date()}: {evo.strip()[:120]}")
            log(f"evolved: {evo.strip()[:80]}")
    append_reflection({
        "action": action,
        "reason": reason,
        "rc": rc,
        "output_tail": out[-500:],
    })

    # store meta update
    meta = store.setdefault("meta", {})
    meta["last_action"] = " ".join(action)
    meta["last_action_ts"] = now.isoformat()
    meta["last_rc"] = rc
    meta["loop_cycles"] = meta.get("loop_cycles", 0) + 1
    save_store(store)

    # human-attention task if the action surfaced something (domain script
    # already posts its own ready tasks; here we only record the cycle).
    return rc


def main():
    global STOP_REQUESTED
    once = "--once" in sys.argv
    interval = DEFAULT_INTERVAL
    for i, a in enumerate(sys.argv):
        if a == "--interval" and i + 1 < len(sys.argv):
            try:
                interval = int(sys.argv[i + 1])
            except ValueError:
                pass

    def stop_handler(sig, frame):
        global STOP_REQUESTED
        STOP_REQUESTED = True
        log("stop requested")
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    log(f"agent_loop started (interval={interval}s, once={once})")
    cycle_count = 0
    while not STOP_REQUESTED:
        try:
            cycle()
            cycle_count += 1
        except Exception as e:
            log(f"cycle error: {e}", "ERROR")
        if once:
            break
        # sleep in small chunks so SIGTERM is responsive
        slept = 0
        while slept < interval and not STOP_REQUESTED:
            time.sleep(5)
            slept += 5
    log(f"agent_loop stopped after {cycle_count} cycles")
    bus("/presence", method="POST", payload={"agent": NAME, "kind": "idle", "note": "loop stopped"})


if __name__ == "__main__":
    main()