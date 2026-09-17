#!/usr/bin/env python3
"""Hostctl — host-side loopback control proxy for the hermes bridge.

Runs on the HOST as rohit on 127.0.0.1:9201. Exposes the host-only
capabilities the n8n-bridge container cannot reach (systemd user units,
the docker socket, host scripts with a correct HOME, code-review-graph,
graphify) as a small authenticated JSON HTTP API.

Why this exists: the bridge runs inside the n8n-bridge container with
host networking, so it CAN reach 127.0.0.1 on the host (like agentbus
on 9107), but it has no sudo, no docker socket, and HOME=/opt/data makes
Path.home() resolve to the wrong place. Host-only Work must be proxied.

Security model:
  - binds loopback only
  - Bearer token must equal BRIDGE_AUTH_KEY from ~/.hermes/.env
  - strictly whitelisted verbs, safe arg charset, no shell=True,
    no free-form arg vectors

Endpoints (all POST JSON):
  /systemctl   {"args": ["status", "hermes-gateway"]}   # --user implied
  /journalctl  {"unit": "hermes-gateway", "lines": 50}
  /docker      {"args": ["ps", "-a", "--format", "..."]}
  /df          {"args": ["-h", "/", "/home"]}
  /crg         {"args": [...], "repo": "hermes-agent", "cwd": "..."}
  /graphify    {"cmd": "path <a> <b>" | "explain <node>"}
  /script      {"name": "unified_cost_guard.py", "args": [...], "timeout": 60}
"""
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "127.0.0.1", 9201
HOME = "/home/rohit"
HERMES_HOME = os.path.join(HOME, ".hermes")
ENV_FILE = os.path.join(HERMES_HOME, ".env")
SCRIPTS_DIR = os.path.join(HERMES_HOME, "scripts")

_TRUE_WORDS = {"yes", "true", "1", "on"}
_ENV_BASE = {
    "HOME": HOME,
    "HERMES_HOME": HERMES_HOME,
    "PATH": "/usr/local/bin:/usr/bin:/bin:/home/rohit/.local/bin",
    "USER": "rohit",
    "LOGNAME": "rohit",
    "LANG": "C.UTF-8",
    "XDG_RUNTIME_DIR": "/run/user/1000",
}


def _read_env(key: str, default: str = ""):
    if not os.path.exists(ENV_FILE):
        return default
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key:
                    v = v.strip().strip('"').strip("'")
                    return v
    except Exception:
        pass
    return default


BRIDGE_AUTH_KEY = _read_env("BRIDGE_AUTH_KEY") or _read_env("N8N_BRIDGE_AUTH_KEY")

SAFE_TOKEN = re.compile(r"^[A-Za-z0-9@:_.\-=/ {}]*$")

SYSTEMCTL_VERBS = {"status", "show", "list-units",
                   "restart", "reset-failed", "is-active", "is-enabled",
                   "list-unit-files", "start", "stop"}
DOCKER_VERBS = {"ps", "images", "logs", "restart", "exec", "inspect",
                "rm", "run", "stats", "top"}
CRG_VERBS = {"status", "graph", "search", "dead-code", "architecture",
             "impact", "flows", "communities", "bridge", "knowledge-gaps",
             "repos", "suggest", "refactor", "query", "path", "explain",
             "detect-changes", "review", "recommend", "confidence", "build",
             "list"}
GRAPHIFY_VERBS = {"path", "explain", "diagnose", "status"}
SCRIPT_ALLOWLIST = {
    "commitment_tracker.py",
    "crg_context.py",
    "decision_ledger.py",
    "hermes_digest.py",
    "human_escalation.py",
    "predictive_signals.py",
    "system_doctor.py",
    "unified_cost_guard.py",
    "unified_memory.py",
}
SCRIPT_MAX_ARGS = 20


def _safe(argv, verbs):
    if not argv or not isinstance(argv, list) or len(argv) > 30:
        return False
    if argv[0] not in verbs:
        return False
    for a in argv[1:]:
        if not isinstance(a, str) or len(a) > 200:
            return False
        if a.startswith("--format") or a.startswith("{{") or "\t" in a:
            continue
        if not SAFE_TOKEN.match(a):
            return False
    return True


def _run(argv, timeout=30, env_extra=None):
    env = dict(os.environ)
    env.update(_ENV_BASE)
    if env_extra:
        env.update(env_extra)
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout, env=env)
        return {"ok": r.returncode == 0, "code": r.returncode,
                "stdout": r.stdout, "stderr": r.stderr}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -1, "stdout": "", "stderr": "timed out"}
    except Exception as e:
        return {"ok": False, "code": -1, "stdout": "", "stderr": str(e)}


def handle_systemctl(payload):
    args = payload.get("args") or []
    if not _safe(args, SYSTEMCTL_VERBS):
        return {"ok": False, "code": -1, "stdout": "", "stderr": "systemctl: verb/args rejected"}
    return _run(["systemctl", "--user", *args], timeout=payload.get("timeout", 30))


def handle_journalctl(payload):
    unit = str(payload.get("unit") or "").strip()
    if not re.match(r"^[A-Za-z0-9@:._\-]+$", unit) or len(unit) > 100:
        return {"ok": False, "code": -1, "stdout": "", "stderr": "journalctl: bad unit"}
    try:
        lines = max(1, min(int(payload.get("lines") or 60), 500))
    except (TypeError, ValueError):
        lines = 60
    return _run(["journalctl", "--user", "-u", unit, "--no-pager", "-n", str(lines)],
                timeout=30)


def handle_docker(payload):
    args = payload.get("args") or []
    if not _safe(args, DOCKER_VERBS):
        return {"ok": False, "code": -1, "stdout": "", "stderr": "docker: verb/args rejected"}
    return _run(["docker", *args], timeout=payload.get("timeout", 45))


def handle_df(payload):
    args = payload.get("args") or ["-h", "/", "/home"]
    safe = args[:10]
    for a in safe:
        if not isinstance(a, str) or len(a) > 100 or not SAFE_TOKEN.match(a):
            return {"ok": False, "code": -1, "stdout": "", "stderr": "df: args rejected"}
    return _run(["df", *safe], timeout=15)


def handle_crg(payload):
    args = payload.get("args") or ["status"]
    if not args or not isinstance(args, list) or len(args) > 30:
        return {"ok": False, "code": -1, "stdout": "", "stderr": "crg: args rejected"}
    crg = os.path.join(HOME, ".local", "bin", "code-review-graph")
    if not os.path.exists(crg):
        crg = "code-review-graph"
    cmd = [crg, *args]
    repo = str(payload.get("repo") or "").strip()
    cwd = str(payload.get("cwd") or "").strip()
    if repo:
        cmd += ["--repo", repo]
    env_extra = {}
    if cwd and re.match(r"^[A-Za-z0-9_\-./]+$", cwd) and os.path.isdir(os.path.join(HOME, cwd)):
        env_extra = {"CRG_REPO_ROOT": os.path.join(HOME, cwd)}
    return _run(cmd, timeout=payload.get("timeout", 120), env_extra=env_extra)


def handle_graphify(payload):
    cmd = str(payload.get("cmd") or "").strip()
    parts = cmd.split()
    if not parts or parts[0] not in GRAPHIFY_VERBS:
        return {"ok": False, "code": -1, "stdout": "", "stderr": "graphify: cmd rejected"}
    for a in parts[1:]:
        if len(a) > 200 or not SAFE_TOKEN.match(a):
            return {"ok": False, "code": -1, "stdout": "", "stderr": "graphify: arg rejected"}
    bin_path = os.path.join(HOME, ".local", "bin", "graphify")
    if not os.path.exists(bin_path):
        bin_path = "graphify"
    return _run([bin_path, *parts], timeout=15,
                env_extra={"GRAPHIFY_HOME": os.path.join(HERMES_HOME, ".graphify")})


def handle_script(payload):
    name = str(payload.get("name") or "").strip()
    if name not in SCRIPT_ALLOWLIST:
        return {"ok": False, "code": -1, "stdout": "", "stderr": f"script: '{name}' not allowed"}
    script = os.path.join(SCRIPTS_DIR, name)
    if not os.path.exists(script):
        return {"ok": False, "code": -1, "stdout": "", "stderr": f"script: {name} not found"}
    args = payload.get("args") or []
    if not isinstance(args, list) or len(args) > SCRIPT_MAX_ARGS:
        return {"ok": False, "code": -1, "stdout": "", "stderr": "script: args rejected"}
    for a in args:
        if not isinstance(a, str) or len(a) > 500 or not SAFE_TOKEN.match(a):
            return {"ok": False, "code": -1, "stdout": "", "stderr": "script: arg rejected"}
    timeout = int(payload.get("timeout") or 60)
    timeout = max(1, min(timeout, 300))
    return _run([sys.executable, script, *args], timeout=timeout,
                env_extra={"HERMES_HOME": HERMES_HOME})


_ENDPOINTS = {
    "/systemctl": handle_systemctl,
    "/journalctl": handle_journalctl,
    "/docker": handle_docker,
    "/df": handle_df,
    "/crg": handle_crg,
    "/graphify": handle_graphify,
    "/script": handle_script,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {BRIDGE_AUTH_KEY}"

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"ok": True, "service": "hostctl"})
        return self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path not in _ENDPOINTS:
            return self._json(404, {"ok": False, "error": "not found"})
        if not self._auth():
            return self._json(401, {"ok": False, "error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw or b"{}")
        except Exception as e:
            return self._json(400, {"ok": False, "error": f"bad json: {e}"})
        try:
            result = _ENDPOINTS[self.path](payload)
        except Exception as e:
            result = {"ok": False, "code": -1, "stdout": "", "stderr": str(e)}
        return self._json(200, result)

    def log_message(self, fmt, *args):
        sys.stderr.write("hostctl: %s\n" % (fmt % args))


def main():
    if not BRIDGE_AUTH_KEY:
        print("hostctl: no BRIDGE_AUTH_KEY (set in %s)" % ENV_FILE, file=sys.stderr)
        sys.exit(1)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"hostctl: listening on {HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()