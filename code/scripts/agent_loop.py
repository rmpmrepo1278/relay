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
PLAYBOOK = os.path.join(HERMES_HOME, "collaborator-memory", "memory", NAME + ".md")
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
    prompt = (
        f"You are the autonomous '{NAME}' homelab agent. Your playbook priorities:\n"
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


def cycle():
    """One autonomous cycle."""
    store = load_store()
    now = datetime.datetime.now(datetime.timezone.utc)

    # presence heartbeat
    bus("/presence", method="POST", payload={
        "agent": NAME, "kind": "working", "note": "autonomous loop cycle"})

    # decide + execute
    action, reason = decide_action()
    if isinstance(action, str):
        action = [action]
    log(f"decided: {action} ({reason})")
    rc, out = execute_domain(action, timeout=300)
    log(f"executed {action}: rc={rc}")

    # reflection entry
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