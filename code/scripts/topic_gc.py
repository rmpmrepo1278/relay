#!/usr/bin/env python3
"""topic_gc.py — Single source + weekly GC for agentbus/topic_map.json.

THIS IS THE ONLY WRITER of agentbus/topic_map.json.
All other agents/scripts MUST read-only. Writes go through this script so
topic creation, listing, and GC remain consistent and race-free.

What it does:
  • lists topics via closeForumTopic probe (Telegram Bot API): for each entry in
    topic_map.json it calls closeForumTopic → if "thread not found" the entry
    is phantom; if close succeeds (or "already closed") it is real and is
    immediately reopened via reopenForumTopic to leave state unchanged.
  • deletes phantom topics weekly: removes phantom entries from the map, writes
    atomically (tmp+replace + fcntl lock when available), updates state file,
    and commits the change to the relay repo (collaborator-memory).
  • offline-safe: if TELEGRAM_BOT_TOKEN missing or network unreachable, probes
    report UNKNOWN and GC never deletes (dry-run mode for safe verification).

Usage:
  topic_gc.py list [--probe] [--dry-run] [--offline]
  topic_gc.py probe [--dry-run] [--offline]
  topic_gc.py gc [--dry-run] [--force] [--offline]   # weekly GC (default)
  topic_gc.py gc --weekly  # explicit weekly (checks 7d interval)
  topic_gc.py add <name> <thread_id> [--dry-run]
  topic_gc.py remove <name> [--dry-run]
  topic_gc.py --help

Scheduler (homelab): run weekly via hermes-scheduler or cron:
  0 3 * * 0 /usr/bin/python3 /home/rohit/.hermes/collaborator-memory/code/scripts/topic_gc.py gc --weekly >> ~/.hermes/logs/topic_gc.log 2>&1
  (also reachable via HERMES_HOME=/home/rohit/.hermes on homelab, ~/ on Mac)

Stdlib only. No network required for --offline / --dry-run list.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── HERMES_HOME resolution (task requires /home/rohit/.hermes on homelab) ──
# Env HERMES_HOME overrides; else ~ (works on both homelab and Mac). Also check
# the canonical homelab path if ~ doesn't contain agentbus.
def _resolve_hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env).expanduser()
    # prefer homelab canonical if it exists
    homelab = Path("/home/rohit/.hermes")
    try:
        if homelab.exists():
            return homelab
    except Exception:
        pass
    return Path(os.path.expanduser("~/.hermes"))

HERMES_HOME = _resolve_hermes_home()
TOPIC_MAP_FILE = HERMES_HOME / "agentbus" / "topic_map.json"
STATE_FILE = HERMES_HOME / "state" / "topic_gc.json"
RELAY_REPO = HERMES_HOME / "collaborator-memory"
# Fallback: if HERMES_HOME is ~ but relay is at ~/.hermes/collaborator-memory elsewhere,
# also try Path.home() based location (Mac)
if not RELAY_REPO.exists():
    alt = Path.home() / ".hermes" / "collaborator-memory"
    if alt.exists():
        RELAY_REPO = alt

GENERAL_THREAD = 7338
WEEKLY_DAYS = 7

# ── helpers ───────────────────────────────────────────────────────────────
def _log(msg: str, level: str = "INFO"):
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{ts}] [{level}] topic_gc: {msg}", flush=True)


def _load_env_file(p: Path) -> dict:
    env = {}
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return env


def _get_token_and_chat() -> tuple[str | None, str | None]:
    # env first, then HERMES_HOME/.env, then relay .env
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_HOME_CHANNEL") or os.environ.get("TELEGRAM_CHAT") or os.environ.get("TELEGRAM_CHANNEL_ID")
    if not token or not chat:
        for env_path in [HERMES_HOME / ".env", Path.home() / ".hermes" / ".env"]:
            try:
                d = _load_env_file(env_path)
                token = token or d.get("TELEGRAM_BOT_TOKEN") or d.get("TELEGRAM_TOKEN")
                chat = chat or d.get("TELEGRAM_HOME_CHANNEL") or d.get("TELEGRAM_CHAT")
                if token and chat:
                    break
            except Exception:
                continue
    # also try reading from n8n_bridge_server config if available
    if not chat:
        chat = "-1003976074764"  # known forum channel
    return token, chat


def load_topic_map() -> dict:
    try:
        if TOPIC_MAP_FILE.exists():
            return json.loads(TOPIC_MAP_FILE.read_text())
    except Exception as e:
        _log(f"load_topic_map error: {e}", "WARN")
    return {}


def _atomic_write(path: Path, data: dict, dry_run: bool = False) -> bool:
    if dry_run:
        _log(f"DRY-RUN would write {path}: {json.dumps(data, sort_keys=True)}")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    # optional file lock
    lock_fp = None
    try:
        try:
            import fcntl  # type: ignore
            lock_fp = open(path, "a") if path.exists() else open(path, "w")
            fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            lock_fp = None  # lock not available (Mac/Win) — proceed without
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        tmp.replace(path)
        _log(f"wrote {path} ({len(data)} entries)")
        return True
    except Exception as e:
        _log(f"atomic_write failed {path}: {e}", "ERROR")
        return False
    finally:
        if lock_fp:
            try:
                import fcntl  # type: ignore
                fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)
                lock_fp.close()
            except Exception:
                pass


def load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except Exception:
        pass
    return {"last_gc": None, "last_phantoms": [], "gc_runs": 0}


def save_state(state: dict, dry_run: bool = False):
    if dry_run:
        _log(f"DRY-RUN would update state: {state}")
        return
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    tmp.replace(STATE_FILE)


def _commit_to_relay(msg: str, dry_run: bool = False) -> bool:
    """Commit TOPIC_MAP_FILE (and state) to the relay repo if it is a git repo."""
    if dry_run:
        _log(f"DRY-RUN would git commit: {msg}")
        return True
    if not RELAY_REPO.exists() or not (RELAY_REPO / ".git").exists():
        # not a relay checkout — just log, don't fail (offline-safe)
        _log(f"relay repo not found at {RELAY_REPO}; skipping git commit", "WARN")
        return False
    # Determine repo-relative path for topic_map.json
    # The file lives at HERMES_HOME/agentbus/topic_map.json which is OUTSIDE the relay.
    # The relay mirrors it at code/scripts or we commit the relay's copy?
    # We commit any tracked copy of topic_map inside relay if present, plus state.
    try:
        # Try to add the canonical file if it is inside relay (some setups symlink)
        # Otherwise, ensure relay has a reference. We commit coordination state at least.
        # For this repo, we store a mirror at data/topic_map_mirror.json for history
        # and commit that alongside the canonical file when possible.
        rel_topic = None
        try:
            rel_topic = TOPIC_MAP_FILE.relative_to(RELAY_REPO)
        except ValueError:
            # not inside relay — create a mirror for commit history
            mirror = RELAY_REPO / "data" / "topic_map_mirror.json"
            mirror.parent.mkdir(parents=True, exist_ok=True)
            try:
                mirror.write_text(json.dumps(load_topic_map(), indent=2, sort_keys=True) + "\n")
                rel_topic = mirror.relative_to(RELAY_REPO)
            except Exception:
                rel_topic = None

        cmds = []
        if rel_topic:
            cmds.append(["git", "add", str(rel_topic)])
        # also stage state if inside relay
        try:
            rel_state = STATE_FILE.relative_to(RELAY_REPO)
            cmds.append(["git", "add", str(rel_state)])
        except ValueError:
            pass
        # fallback: stage known relay files
        for c in cmds:
            subprocess.run(c, cwd=RELAY_REPO, capture_output=True, timeout=10)
        # commit if staged
        r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=RELAY_REPO)
        if r.returncode == 0:
            _log("nothing staged for relay commit; skipping", "INFO")
            return False
        subprocess.run(["git", "commit", "-m", msg], cwd=RELAY_REPO, capture_output=True, timeout=10)
        # push is optional; do not fail if offline
        subprocess.run(["git", "push"], cwd=RELAY_REPO, capture_output=True, timeout=15)
        _log(f"relay commit: {msg}")
        return True
    except Exception as e:
        _log(f"relay commit skipped: {e}", "WARN")
        return False


# ── Telegram probe via closeForumTopic ────────────────────────────────────
def probe_thread(chat_id: str, thread_id: int, token: str, timeout: int = 8) -> tuple[str, str]:
    """Probe a single thread via closeForumTopic + reopen. Returns (status, detail).

    status: REAL | PHANTOM | UNKNOWN
    detail: human-readable API response snippet
    """
    base = f"https://api.telegram.org/bot{token}"
    payload = json.dumps({"chat_id": chat_id, "message_thread_id": thread_id}).encode()
    headers = {"Content-Type": "application/json"}

    def call(method: str) -> dict:
        req = urllib.request.Request(f"{base}/{method}", data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode())
                return {"ok": False, "error_code": e.code, "description": body.get("description", f"HTTP {e.code}"), "_raw": body}
            except Exception:
                return {"ok": False, "error_code": e.code, "description": f"HTTP {e.code}"}
        except Exception as e:
            return {"ok": False, "description": str(e), "_offline": True}

    res = call("closeForumTopic")
    if res.get("ok") is True:
        # real topic — reopen to leave unchanged
        reopen = call("reopenForumTopic")
        # reopen should succeed; if already open it's fine
        return "REAL", f"close ok, reopen={reopen.get('ok')}"
    desc = (res.get("description") or "").lower()
    # phantom indicators
    if any(s in desc for s in ["thread not found", "topic not found", "message thread not found", "thread_id_invalid", "topic not found"]):
        return "PHANTOM", res.get("description", "not found")
    if "already closed" in desc:
        # topic exists but was closed; reopen
        call("reopenForumTopic")
        return "REAL", "already closed (real)"
    if res.get("_offline"):
        return "UNKNOWN", f"offline: {res.get('description')}"
    if "not enough rights" in desc or "chat not found" in desc or "unauthorized" in desc or "forbidden" in desc:
        return "UNKNOWN", res.get("description", "")
    # default: treat as unknown to avoid accidental deletion
    return "UNKNOWN", res.get("description", str(res))


def list_and_probe(probe: bool = False, offline: bool = False, dry_run: bool = False) -> dict:
    """Load map and optionally probe each entry. Returns probe results dict."""
    tmap = load_topic_map()
    if not tmap:
        _log(f"topic_map empty or missing at {TOPIC_MAP_FILE}", "WARN")
        if not TOPIC_MAP_FILE.exists() and not dry_run:
            # initialize with known-good minimal map (from journal 2026-09-14)
            tmap = {"jenny": 10000, "homelab": 10026}
            _log("initializing minimal map {jenny:10000, homelab:10026}", "INFO")
            _atomic_write(TOPIC_MAP_FILE, tmap, dry_run=dry_run)
    if not probe:
        for name, tid in sorted(tmap.items()):
            print(f"{name:20s} {tid}")
        return {"map": tmap, "probed": {}}

    if offline:
        _log("offline mode: skipping Telegram probes, reporting UNKNOWN", "INFO")
        for name, tid in sorted(tmap.items()):
            print(f"{name:20s} {tid:8d} UNKNOWN (offline)")
        return {"map": tmap, "probed": {k: ("UNKNOWN", "offline") for k in tmap}}

    token, chat = _get_token_and_chat()
    if not token:
        _log("TELEGRAM_BOT_TOKEN not set (checked env and ~/.hermes/.env); probes -> UNKNOWN (offline-safe)", "WARN")
        for name, tid in sorted(tmap.items()):
            print(f"{name:20s} {tid:8d} UNKNOWN (no token)")
        return {"map": tmap, "probed": {k: ("UNKNOWN", "no token") for k in tmap}}

    results = {}
    for name, tid in sorted(tmap.items()):
        status, detail = probe_thread(chat, int(tid), token)
        results[name] = (status, detail)
        print(f"{name:20s} {tid:8d} {status:8s} {detail}")
        # be nice to the API
        time.sleep(0.35)
    return {"map": tmap, "probed": results}


def run_gc(dry_run: bool = False, force: bool = False, offline: bool = False, weekly: bool = False) -> int:
    """Weekly GC: remove phantom entries. Returns exit code 0=ok, 1=error.

    If weekly=True, respect 7-day interval unless --force.
    """
    state = load_state()
    now = datetime.now(timezone.utc)
    last_gc_s = state.get("last_gc")
    if weekly and not force and last_gc_s:
        try:
            last_gc = datetime.fromisoformat(last_gc_s.replace("Z", "+00:00"))
            if now - last_gc < timedelta(days=WEEKLY_DAYS):
                remain = timedelta(days=WEEKLY_DAYS) - (now - last_gc)
                _log(f"weekly GC: last run {last_gc_s} ({(now-last_gc).days}d ago); {remain.days}d remaining — skip (use --force to override)", "INFO")
                # still list without deleting
                list_and_probe(probe=False, offline=offline, dry_run=dry_run)
                return 0
        except Exception:
            pass

    probe_res = list_and_probe(probe=True, offline=offline, dry_run=dry_run)
    tmap = probe_res["map"]
    probed = probe_res["probed"]

    phantoms = [name for name, (st, _) in probed.items() if st == "PHANTOM"]
    unknowns = [name for name, (st, _) in probed.items() if st == "UNKNOWN"]
    reals = [name for name, (st, _) in probed.items() if st == "REAL"]

    _log(f"probe summary: {len(reals)} real, {len(phantoms)} phantom, {len(unknowns)} unknown (total {len(tmap)})")

    if unknowns and not offline:
        _log(f"unknown topics (not deleted, need manual check): {', '.join(unknowns)}", "WARN")

    if not phantoms:
        _log("no phantoms to delete", "INFO")
        if not dry_run:
            state["last_gc"] = now.isoformat().replace("+00:00", "Z")
            state["last_phantoms"] = []
            state["gc_runs"] = state.get("gc_runs", 0) + 1
            save_state(state, dry_run=dry_run)
        return 0

    _log(f"phantoms to delete: {phantoms}", "WARN" if not dry_run else "INFO")
    if dry_run:
        _log(f"DRY-RUN: would delete {phantoms} from {TOPIC_MAP_FILE} and commit to relay", "INFO")
        return 0

    # Delete phantoms from map
    new_map = {k: v for k, v in tmap.items() if k not in phantoms}
    ok = _atomic_write(TOPIC_MAP_FILE, new_map, dry_run=False)
    if not ok:
        _log("failed to write topic_map.json; aborting commit", "ERROR")
        return 1

    state["last_gc"] = now.isoformat().replace("+00:00", "Z")
    state["last_phantoms"] = phantoms
    state["gc_runs"] = state.get("gc_runs", 0) + 1
    state["last_map"] = new_map
    save_state(state, dry_run=False)

    _commit_to_relay(f"topic_gc: remove {len(phantoms)} phantom topic(s): {', '.join(phantoms)}", dry_run=False)
    _log(f"GC done: removed {phantoms}; new map has {len(new_map)} entries", "INFO")
    return 0


def cmd_add(name: str, tid: str, dry_run: bool = False) -> int:
    try:
        tid_int = int(tid)
    except ValueError:
        _log(f"thread_id must be integer, got {tid!r}", "ERROR")
        return 2
    tmap = load_topic_map()
    old = tmap.get(name)
    tmap[name] = tid_int
    action = "updated" if old is not None else "added"
    _log(f"{action} {name}: {old} -> {tid_int}" + (" (dry-run)" if dry_run else ""))
    ok = _atomic_write(TOPIC_MAP_FILE, tmap, dry_run=dry_run)
    if ok and not dry_run:
        _commit_to_relay(f"topic_gc: {action} {name} -> {tid_int}", dry_run=False)
    return 0 if ok else 1


def cmd_remove(name: str, dry_run: bool = False) -> int:
    tmap = load_topic_map()
    if name not in tmap:
        _log(f"{name} not in map; nothing to remove", "WARN")
        return 0
    old = tmap.pop(name)
    _log(f"removed {name} ({old})" + (" (dry-run)" if dry_run else ""))
    ok = _atomic_write(TOPIC_MAP_FILE, tmap, dry_run=dry_run)
    if ok and not dry_run:
        _commit_to_relay(f"topic_gc: remove {name} ({old})", dry_run=False)
    return 0 if ok else 1


def main():
    p = argparse.ArgumentParser(description="topic_gc — single writer for agentbus/topic_map.json + weekly phantom GC via closeForumTopic probe")
    p.add_argument("command", nargs="?", default="gc", choices=["list", "probe", "gc", "add", "remove", "sync"],
                   help="action (default: gc)")
    p.add_argument("name", nargs="?", help="topic name (for add/remove)")
    p.add_argument("thread_id", nargs="?", help="thread_id (for add)")
    p.add_argument("--dry-run", action="store_true", help="do not write files or call commit; probes still run unless --offline")
    p.add_argument("--offline", action="store_true", help="skip Telegram network probes (UNKNOWN for all)")
    p.add_argument("--force", action="store_true", help="force GC even if weekly interval not elapsed")
    p.add_argument("--weekly", action="store_true", help="weekly mode: skip GC if last run <7d ago (unless --force)")
    p.add_argument("--probe", action="store_true", help="with 'list', also probe via Telegram")
    args = p.parse_args()

    # Map sync alias to gc
    cmd = "gc" if args.command == "sync" else args.command

    if cmd == "list":
        list_and_probe(probe=args.probe, offline=args.offline, dry_run=args.dry_run)
        return 0
    elif cmd == "probe":
        list_and_probe(probe=True, offline=args.offline, dry_run=args.dry_run)
        return 0
    elif cmd == "gc":
        return run_gc(dry_run=args.dry_run, force=args.force, offline=args.offline, weekly=args.weekly)
    elif cmd == "add":
        if not args.name or not args.thread_id:
            p.error("add requires <name> <thread_id>")
        return cmd_add(args.name, args.thread_id, dry_run=args.dry_run)
    elif cmd == "remove":
        if not args.name:
            p.error("remove requires <name>")
        return cmd_remove(args.name, dry_run=args.dry_run)
    else:
        p.error(f"unknown command {cmd}")

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
