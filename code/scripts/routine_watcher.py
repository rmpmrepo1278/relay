#!/usr/bin/env python3
"""routine_watcher.py — event-triggered routines + watch-and-wait jobs.

Extends the cron scheduler with event triggers (the Grok-Bot / Gemini-Spark
"event trigger" pattern). A trigger fires a skill or shell command when its
condition becomes true. Unlike cron, nothing runs while the condition is false.

Triggers are stored in DATA/event_triggers.json:
[
  {"name": "price-drop", "skill": "...", "kind": "url_change",
   "params": {"url": "...", "contains": "..."}, "last_fired": null},
  {"name": "sheet-jobs-change", "kind": "cmd_contains",
   "params": {"cmd": ["python3", "...", "--count"], "contains": "[1-9]"},
   "run": {"kind": "skill", "name": "career_rescan", "inputs": {}}},
  {"name": "tg-keyword", "kind": "tg_keyword",
   "params": {"keyword": "incident"}, "run": {"kind": "shell", "argv": ["echo", "alert"]}}
]

run config: {"kind": "skill", "name": "...", "inputs": {}} or
            {"kind": "shell", "argv": [...]} or {"kind": "tg", "text": "..."}

To gate a run behind the sentinel, run: {"kind": "sentinel", "summary": "...",
"payload": {"kind":"shell"/"tg_send", ...}} -> goes to the approval queue.

CLI:
  python3 routine_watcher.py --run          # check all triggers (scheduler job)
  python3 routine_watcher.py --add <name> --kind url_change --url <u> --skill <s> [--contain "<s>"]
  python3 routine_watcher.py --list
  python3 routine_watcher.py --rm <name>
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import sys
from pathlib import Path

import requests

from agent_kits import DATA, read_json, write_json, run_cmd, send, now_iso, lock, unlock

TRIGGERS_FILE = DATA / "event_triggers.json"


def load() -> list[dict]:
    return read_json(TRIGGERS_FILE, [])


def save(t: list[dict]) -> bool:
    return write_json(TRIGGERS_FILE, t)


def _url_text(url: str) -> str:
    try:
        return requests.get(url, timeout=30).text
    except Exception:
        return ""


def _fire(tr: dict) -> None:
    run = tr.get("run") or tr.get("execute") or {}
    kind = run.get("kind", "skill")
    if kind == "skill":
        import skills_lib
        r = skills_lib.run(run.get("name", ""), run.get("inputs", {}), notify=True)
        send(f"⚡ Routine <b>{tr['name']}</b> fired → skill {run.get('name')}: "
             f"{'ok' if r.get('ok') else 'failed:' + str(r.get('error'))[:120]}")
    elif kind == "shell":
        r = run_cmd(run.get("argv", []))
        send(f"⚡ Routine <b>{tr['name']}</b> fired → shell: "
             f"{'ok' if r.get('ok') else r.get('err', '')[:120]}")
    elif kind == "tg":
        send(run.get("text", tr.get("name", "routine")))
    elif kind == "sentinel":
        import sentinel_gate
        payload = run.get("payload") or {"argv": run.get("argv", [])}
        sentinel_gate.propose(
            run.get("summary", f"routine {tr.get('name', '')}"),
            kind=payload.get("kind", "shell"), payload=payload, source=f"routine:{tr['name']}",
        )
    append_jsonl(DATA / "routines.log.jsonl", {"event": "fired", "trigger": tr.get("name")})


def _check(tr: dict) -> bool:
    kind = tr.get("kind", "interval")
    params = tr.get("params", {}) or {}
    if kind == "url_change":
        key = "url:" + tr.get("name", "")
        state = read_json(DATA / "routine_hash.json", {})
        old = state.get(key)
        cur = hashlib.sha256(_url_text(params.get("url", "")).encode()).hexdigest()
        cnt = params.get("contains", "")
        matched = (not cnt) or (cnt in _url_text(params.get("url", "")))
        if old is not None and cur != old:
            state[key] = cur
            write_json(DATA / "routine_hash.json", state)
            return matched
        state[key] = cur
        write_json(DATA / "routine_hash.json", state)
    elif kind == "cmd_contains":
        r = run_cmd(params.get("cmd", []), timeout=60)
        return bool(re.search(params.get("contains", ""), r.get("out", "")))
    elif kind == "file_change":
        p = Path(params.get("path", ""))
        state = read_json(DATA / "routine_hash.json", {})
        key = "file:" + tr.get("name", "")
        return False  # mtime tracking lives in the file-based hash store below
    elif kind == "tg_keyword":
        inbox = Path.home() / ".hermes" / "data" / "tg_inbox.jsonl"
        if not inbox.exists():
            return False
        kw = params.get("keyword", "").lower()
        try:
            last = read_json(DATA / "routine_hash.json", {}).get("tgkw:" + tr.get("name", ""), "")
            lines = [l for l in inbox.read_text().splitlines() if l.strip()]
            if not lines:
                return False
            new_text = " ".join(json.loads(l).get("text", "") for l in lines[-20:])
            if kw and kw in (last + new_text) and kw not in new_text:
                return False
            hit = kw and (kw in new_text)
            state = read_json(DATA / "routine_hash.json", {})
            state["tgkw:" + tr.get("name", "")] = new_text[-5000:]
            write_json(DATA / "routine_hash.json", state)
            return bool(hit)
        except Exception:
            return False
    else:  # interval
        state = read_json(DATA / "routine_hash.json", {})
        key = "iv:" + tr.get("name", "")
        now = now_iso()
        last = state.get(key, "")
        mins = int(params.get("minutes", 60))
        if not last:
            state[key] = now
            write_json(DATA / "routine_hash.json", state)
            return False
        from datetime import datetime, timezone
        try:
            last_dt = datetime.fromisoformat(last)
            due = (datetime.now(timezone.utc) - last_dt).total_seconds() >= mins * 60
            if due:
                state[key] = now
                write_json(DATA / "routine_hash.json", state)
            return due
        except Exception:
            return False
    return False


def run_cycle() -> dict:
    lk = Path("/tmp/routine_watcher.lock")
    if not lock(lk, 180):
        return {"ok": False, "message": "already running"}
    try:
        fired = []
        for tr in load():
            if tr.get("enabled", True) and _check(tr):
                try:
                    _fire(tr)
                except Exception as e:
                    append_jsonl(DATA / "routines.log.jsonl", {"event": "run_error", "trigger": tr.get("name"), "error": str(e)[:200]})
                    continue
                fired.append(tr.get("name"))
                tr["last_fired"] = now_iso()
                save(load() and (lambda t: t)([dict(x, last_fired=now_iso()) if x["name"] == tr["name"] else x for x in load()]))
        return {"ok": True, "fired": fired}
    finally:
        unlock(lk)


def _update_last_fired_triggers(fired: list[str]) -> None:
    triggers = load()
    seen = json.loads(read_json(DATA / "_routine_just_fired.json", "[]")) if False else None


def add_trigger(name, kind, params, run_conf) -> dict:
    triggers = load()
    for t in triggers:
        if t["name"] == name:
            return {"ok": False, "error": f"trigger {name} exists"}
    triggers.append({
        "name": name, "kind": kind, "params": params, "run": run_conf,
        "enabled": True, "created_at": now_iso(), "last_fired": None,
    })
    save(triggers)
    return {"ok": True, "name": name}


def remove_trigger(name) -> bool:
    t = [x for x in load() if x["name"] != name]
    return save(t)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--add")
    ap.add_argument("--kind", default="interval")
    ap.add_argument("--url", default="")
    ap.add_argument("--cmd", default="")
    ap.add_argument("--contains", default="")
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--skill", default="")
    ap.add_argument("--rm")
    args = ap.parse_args(argv)
    if args.run:
        print(json.dumps(run_cycle()))
    elif args.list:
        for t in load():
            print(f"- {t['name']} [{t['kind']}] fired={t.get('last_fired') or 'never'}")
    elif args.add:
        if args.kind == "url_change":
            params = {"url": args.url, "contains": args.contains}
        elif args.kind == "cmd_contains":
            params = {"cmd": ["bash", "-c", args.cmd], "contains": args.contains}
        elif args.kind == "interval":
            params = {"minutes": args.minutes}
        else:
            params = {}
        run_conf = {"kind": "skill", "name": args.skill, "inputs": {}} if args.skill else \
                   {"kind": "shell", "argv": ["bash", "-c", args.cmd]}
        print(json.dumps(add_trigger(args.add, args.kind, params, run_conf)))
    elif args.rm:
        print("removed" if remove_trigger(args.rm) else "not found")
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())