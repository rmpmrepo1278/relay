#!/usr/bin/env python3
"""regression_test.py - pre-commit regression checks for Hermes/Telegram flows."""
import json
import os
import sys
import glob
import time
import urllib.request
import urllib.error
from pathlib import Path

_BRIDGE = os.environ.get("TELEGRAM_BRIDGE_URL", "http://127.0.0.1:9199")
_DEFAULT_CHAT = os.environ.get("TELEGRAM_HOME_CHANNEL", "-1003976074764")
def _bridge_key() -> str:
    k = os.environ.get("BRIDGE_AUTH_KEY")
    if k:
        return k
    try:
        for line in Path("/home/rohit/.hermes/.env").read_text().splitlines():
            if line.startswith("BRIDGE_AUTH_KEY="):
                return line.partition("=")[2]
    except Exception:
        pass
    return ""


_AUTH = "Bearer " + _bridge_key()


def _env_file(name):
    """Mirror the bridge's env resolution: os.environ first, then ~/.hermes/.env."""
    v = os.environ.get(name)
    if v:
        return v
    try:
        for line in Path("/home/rohit/.hermes/.env").read_text().splitlines():
            key, _, val = line.partition("=")
            if key == name and val:
                return val
    except Exception:
        pass
    return None


def _post(ep, d, t=15):
    import urllib.request
    url = _BRIDGE + ep
    body = json.dumps(d).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Authorization": _AUTH},
    )
    try:
        with urllib.request.urlopen(req, timeout=t) as r:
            return True, json.loads(r.read())
    except Exception as e:
        return False, {"status": "error", "message": str(e)}


def _send_tg(text, cid=None):
    import time as _t
    ok, p = _post("/telegram-send", {
        "text": f"{text} [{_t.strftime('%m%d%H%M%S')}]",
        "chat_id": cid or _DEFAULT_CHAT,
        "parse_mode": "HTML",
    })
    if not ok:
        return False, p
    # Bridge returns {"status":"ok","throttled":true,"category":...} without a
    # "response" payload when the send was accepted but throttled; otherwise
    # {"status":"ok","response":{...}} where response=Telegram's payload.
    if p.get("throttled"):
        return True, p
    # Deduped = bridge accepted an identical recent message (reachability + auth
    # OK); unique per-run timestamp makes this rare, but never a false FAIL.
    if p.get("deduped"):
        return True, p
    resp = p.get("response", {}) if isinstance(p, dict) else {}
    tg_ok = resp.get("ok") is True
    mid = resp.get("result", {}).get("message_id", "?")
    return tg_ok, mid


def _retrieve(label, fn):
    try:
        code, detail = fn()
        prefix = "PASS:" if code == 0 else "FAIL:"
        return (code, f"{prefix} {detail}")
    except Exception as e:
        return (1, f"ERROR: {str(e)[:150]}")


# --- Tests ---

def test_bridge_ping():
    ok, p = _post("/ping", {"text": "ping"})
    if not ok:
        return 1, p.get("message", "?")[:80]
    pong = (p.get("pong") is True or p.get("status") == "ok")
    return (0 if pong else 1, f"pong={pong}")


def test_telegram_send():
    ok, detail = _send_tg("regression test")
    if isinstance(detail, dict) and detail.get("status") == "ok":
        # Bridge accepted the message. A throttled/deduped send never touches
        # api.telegram.org, so this proves bridge reachability + auth ONLY.
        # Real delivery is asserted by tg-egress below.
        return 0, f"bridge accepted (throttled={detail.get('throttled', False)} cat={detail.get('category', '?')})"
    if ok:
        return 0, f"bridge sent msg_id={detail}"
    return 1, str(detail)[:80]


def test_telegram_egress():
    """REAL Telegram egress: sendMessage straight to api.telegram.org with the
    same token the bridge loads, require ok:true + message_id (delivered), then
    deleteMessage to self-clean. This is the check tg-send's throttle-acceptance
    could never catch — Round-9: TELEGRAM_BOT_TOKEN never loaded in the bridge,
    so every send was a silent botNone/getUpdates-style 404 while the bridge
    poller looked healthy. A plain bridge OK must no longer count as delivery."""
    token = _env_file("TELEGRAM_BOT_TOKEN")
    if not token:
        return 1, "TELEGRAM_BOT_TOKEN missing from .env -> egress impossible (Round-9 failure mode)"
    chat = _env_file("TELEGRAM_HOME_CHANNEL") or _DEFAULT_CHAT
    thread = _env_file("TELEGRAM_HOME_CHANNEL_THREAD_ID")
    payload = {"chat_id": chat, "message_thread_id": int(thread),
               "text": f"regression egress probe {time.strftime('%m%d%H%M%S')} (auto-deleted)"}
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode() or "{}")
            desc = body.get("description", e)
        except Exception:
            desc = e
        return 1, f"egress FAIL (HTTP {e.code}): {desc}"
    except Exception as e:
        return 1, f"egress FAIL (send): {str(e)[:140]}"
    if not resp.get("ok"):
        return 1, f"egress FAIL: {resp.get('description', '?')[:140]}"
    mid = resp.get("result", {}).get("message_id")
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/deleteMessage",
            data=json.dumps({"chat_id": chat, "message_id": mid}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=20)
    except Exception:
        pass
    return 0, f"egress OK: delivered to chat {chat} (thread {thread}), msg_id={mid}, deleted"


def test_docker_ps():
    import subprocess
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=30,
        )
        names = [n for n in r.stdout.splitlines() if n]
        critical = {"hermes", "healthchecks"}
        missing = critical - set(names)
        if missing:
            return 1, f"missing critical: {missing}"
        return 0, f"{len(names)} containers, critical OK"
    except Exception as e:
        return 1, str(e)[:120]


def test_autoheal():
    """Autoheal is the self-healing watcher (replaces ollama's watchdog role).
    Must be running so unhealthy containers get restarted automatically."""
    import subprocess
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=30,
        )
        names = [n.strip() for n in r.stdout.splitlines() if n.strip()]
        if "autoheal" not in names:
            return 1, "autoheal container not running"
        return 0, "autoheal running"
    except Exception as e:
        return 1, str(e)[:120]


def test_inventory():
    # Source of truth: ~/services/inventory/inventory.json (generated by inventory.py)
    inv = "/home/rohit/services/inventory/inventory.json"
    if not os.path.exists(inv):
        return 1, "inventory.json missing"
    try:
        with open(inv) as f:
            data = json.load(f)
        # Accept list or dict-with-services
        n = len(data) if isinstance(data, list) else len(data.get("services", {}))
        return 0, f"inventory.json OK ({n} services)"
    except Exception as e:
        return 1, f"bad json: {str(e)[:80]}"


def test_ask():
    ok, p = _post("/ask", {"text": "/ask --category infra hello", "category": "infra"})
    if not ok:
        return 1, p.get("message", "?")[:80]
    # Bridge returns {"text": "..."} directly; for direct HTTP use it exposes the
    # usage banner or an answer. Reachability is the meaningful pre-commit signal.
    t = p.get("text", "") or ""
    usage = "Usage:" in t[:80]
    if not t:
        return 1, "empty response"
    if usage:
        # Endpoint reachable + parses command routing; banner = expected for raw HTTP.
        return 0, "endpoint OK (usage banner - normal for raw bridge call)"
    if "\u274c" in t[:30]:
        return 1, t[:120]
    return 0, f"ok len={len(t)}"



def test_gdrive_owned():
    """Assert gdrive: is authed to rohitmishra1278@gmail.com and its root
    is an OWNED tree containing the 'Job Hunt' folder (not a shared-with-me
    duplicate). Regression: forces the push target to resolve as owned content."""
    import subprocess
    try:
        r = subprocess.run(
            ["rclone", "lsf", "-d", "gdrive:/"],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return 1, "rclone missing"
    except Exception as e:
        return 1, str(e)[:120]
    if r.returncode != 0:
        err = (r.stderr or r.stdout)[:160]
        if "empty token" in err or "401" in err or "failed to make oauth" in err:
            return 1, "gdrive token expired/shared-client. Run: rclone config reconnect gdrive: --drive-auth-url https://accounts.google.com/o/oauth2/auth"
        return 1, err
    top = [l.strip().rstrip("/") for l in r.stdout.splitlines() if l.strip()]
    if not any(x.lower() == "job hunt" for x in top):
        return 1, "Job Hunt NOT at gdrive: owned root -> %s (shared-with-me drift?)" % (top[:8],)
    return 0, "owned root OK: %s" % (top[:5],)



def test_homelab_backups():
    """Real kopia probe via homelab_agent.check_backups() (sudo -n kopia:
    repo lives under root's config). Guards the Round-10 fixes: stream JSON
    parse (was reading 1 snapshot / oldest) + sudo path (was "not_configured"
    false alarm). Sleeps through the 6h verify throttle — this only reads."""
    import subprocess
    scripts = str(Path(__file__).resolve().parent)
    code = (
        "import sys, json; sys.path.insert(0, sys.argv[1]); import homelab_agent as h; "
        "print(json.dumps(h.check_backups()))"
    )
    try:
        r = subprocess.run(
            [sys.executable, "-c", code, scripts],
            capture_output=True, text=True, timeout=90,
        )
    except Exception as e:
        return 1, str(e)[:120]
    if r.returncode != 0:
        return 1, (r.stderr or r.stdout)[:140]
    try:
        b = json.loads(r.stdout.strip())
    except Exception:
        return 1, f"bad check_backups output: {r.stdout[:140]}"
    st = b.get("status")
    if st != "healthy":
        return 1, f"backups {st}: {json.dumps(b)[:160]}"
    if b.get("total_snapshots", 0) < 1:
        return 1, "backups healthy but 0 snapshots parsed (stream parse regression?)"
    return 0, f"kopia OK: {b.get('total_snapshots')} snaps, newest age {b.get('age_hours')}h"


ALL_TESTS = [
    ("bridge-ping", test_bridge_ping),
    ("tg-send", test_telegram_send),
    ("tg-egress", test_telegram_egress),
    ("docker-ps", test_docker_ps),
    ("autoheal", test_autoheal),
    ("inventory", test_inventory),
    ("ask-func", test_ask),
    ("gdrive-owned", test_gdrive_owned),
    ("homelab-backups", test_homelab_backups),
]


def main():
    passed = failed = 0
    for label, fn in ALL_TESTS:
        code, detail = _retrieve(label, fn)
        status = "PASS" if code == 0 else "FAIL"
        if code == 0:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {label}: {detail}")

    print()
    if failed == 0:
        print(f"ALL PASSED ({passed}/{passed})")
    else:
        print(f"FAILURES: {failed} failed, {passed} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
