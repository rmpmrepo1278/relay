#!/usr/bin/env python3
"""sentinel_gate.py — approval gate for consequential agent actions.

Mirrors the Meta-Muse Sentinel / Grok-Bot review-agent pattern: the agent
proposes an action, the human approves/denies/always-allows from Telegram, and
only then is the action executed. Deny by default; nothing external happens
without an explicit OK.

State:
  DATA/agent_actions.json   list of action records
  DATA/agent_action_rules.json  always-allow rules { "<kind>::<pattern>": {...} }

Kinds:
  shell    payload {"argv": [...]}      executes a subprocess
  tg_send  payload {"text": "..."}      sends a Telegram message
  none     payload {}                   just marks done (bookkeeping)

CLI:
  python3 sentinel_gate.py --propose "<summary>" --kind shell --argv "ls -la"
  python3 sentinel_gate.py --approve <id> | --deny <id> | --always <id>
  python3 sentinel_gate.py --list [--pending]
  python3 sentinel_gate.py --run        # execute all approved, not yet run
  python3 sentinel_gate.py --status
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent_kits import (
    DATA, read_json, write_json, append_jsonl, trim_jsonl, lock, unlock, send, run_cmd,
    mask_value, now_iso,
)

ACTIONS_FILE = DATA / "agent_actions.json"
RULES_FILE = DATA / "agent_action_rules.json"


def _load() -> list[dict]:
    return read_json(ACTIONS_FILE, [])


def _save(actions: list[dict]) -> bool:
    return write_json(ACTIONS_FILE, actions)


def _load_rules() -> dict:
    return read_json(RULES_FILE, {})


def _save_rules(rules: dict) -> bool:
    return write_json(RULES_FILE, rules)


def _rule_key(kind: str, pattern: str) -> str:
    return f"{kind}::{pattern}"


def rule_match(record: dict) -> bool:
    """True when an always-allow rule covers this action. Deny by default."""
    rules = _load_rules()
    kind = record.get("kind", "")
    summary = record.get("summary", "") or ""
    payload = record.get("payload", {}) or {}
    text = f"{summary}\n{payload.get('text', '')}\n{payload.get('argv', '')}"
    for key, rule in rules.items():
        if not rule.get("allow"):
            continue
        key_kind, _, pat = key.partition("::")
        if key_kind != kind:
            continue
        if not pat:
            return True  # bare kind rule allows the whole kind
        if pat in text or pat in summary:
            return True
    return False


def propose(summary: str, kind: str = "shell", payload: dict | None = None,
            source: str = "agent", require_approval: bool = True,
            notify: bool = True, chat_id: str | None = None) -> dict:
    """Register a proposed action. Auto-approves when an always-allow rule hits."""
    payload = payload or {}
    record = {
        "id": uuid.uuid4().hex[:8],
        "summary": summary[:250],
        "kind": kind,
        "payload": payload,
        "source": source,
        "status": "pending",
        "created_at": now_iso(),
        "ran_at": None,
        "result": None,
        "always_rule": False,
        "chat_id": chat_id,
    }
    actions = _load()
    if not require_approval or rule_match(record):
        record["status"] = "approved"
        record["always_rule"] = True
    actions.append(record)
    _save(actions)
    append_jsonl(DATA / "sentinel.log.jsonl", {"event": "propose", "id": record["id"],
                                               "kind": kind, "status": record["status"]})
    trim_jsonl(DATA / "sentinel.log.jsonl", 2000)
    if notify:
        suffix = " (auto-approved by rule)" if record["status"] == "approved" else \
            f"\n/approve {record['id']} · /deny {record['id']} · /always {record['id']}"
        send(
            f"🧠 Action proposed [#{record['id']}] <b>{record['summary']}</b>\n"
            f"kind: {kind}{suffix}",
            chat_id=chat_id,
        )
    return record


def _get(action_id: str) -> dict | None:
    for a in _load():
        if a.get("id") == action_id:
            return a
    return None


def approve(action_id: str) -> dict:
    actions = _load()
    for a in actions:
        if a.get("id") == action_id:
            if a.get("status") == "running":
                return {"ok": False, "message": "already running"}
            a["status"] = "approved"
            a["approved_at"] = now_iso()
            _save(actions)
            append_jsonl(DATA / "sentinel.log.jsonl", {"event": "approve", "id": action_id})
            return {"ok": True, "message": f"approved #{action_id}", "record": a}
    return {"ok": False, "message": f"no action #{action_id}"}


def deny(action_id: str) -> dict:
    actions = _load()
    for a in actions:
        if a.get("id") == action_id and a.get("status") != "running":
            a["status"] = "denied"
            a["denied_at"] = now_iso()
            _save(actions)
            append_jsonl(DATA / "sentinel.log.jsonl", {"event": "deny", "id": action_id})
            return {"ok": True, "message": f"denied #{action_id}"}
    return {"ok": False, "message": f"no actionable #{action_id}"}


def always(action_id: str) -> dict:
    """Approve AND save an always-allow rule so future lookalikes skip the gate."""
    actions = _load()
    for a in actions:
        if a.get("id") == action_id and a.get("status") != "running":
            a["status"] = "approved"
            a["always_rule"] = True
            a["approved_at"] = now_iso()
            rules = _load_rules()
            base = a.get("summary", "").split("(")[0].strip()[:120]
            key = _rule_key(a.get("kind", ""), base)
            rules[key] = {"allow": True, "created_by": a.get("source"), "at": now_iso()}
            _save_rules(rules)
            _save(actions)
            append_jsonl(DATA / "sentinel.log.jsonl", {"event": "always", "id": action_id, "rule": key})
            return {"ok": True, "message": f"approved #{action_id} + always-allow rule saved"}
    return {"ok": False, "message": f"no actionable #{action_id}"}


def _execute(record: dict) -> dict:
    kind = record.get("kind", "none")
    payload = record.get("payload", {}) or {}
    start = time.time()
    if kind == "shell":
        argv = payload.get("argv", [])
        if isinstance(argv, str):
            argv = argv.split()
        res = run_cmd(argv, timeout=payload.get("timeout", 300))
        result = {
            "ok": res["ok"], "code": res["code"],
            "out": res["out"][:1500], "err": res["err"][:1000],
            "elapsed_s": round(time.time() - start, 1),
        }
    elif kind == "tg_send":
        ok = send(payload.get("text", "(empty)"), chat_id=record.get("chat_id"))
        result = {"ok": ok, "code": 0 if ok else -1, "out": "sent", "err": "", "elapsed_s": 0}
    elif kind == "skills":
        try:
            import skills_lib
            parts_res = skills_lib.run(payload.get("name", ""), payload.get("inputs", {}),
                                       notify=False, bypass_approval=True)
            result = {"ok": parts_res.get("ok", False), "code": 0 if parts_res.get("ok") else 1,
                      "out": parts_res.get("output", parts_res.get("message", ""))[:1500],
                      "err": parts_res.get("error", ""), "elapsed_s": round(time.time() - start, 1)}
        except Exception as e:  # defensive
            result = {"ok": False, "code": -3, "out": "", "err": str(e)[:1000], "elapsed_s": 0}
    elif kind == "emailTriage":
        try:
            import email_intelligence as ei
            to = payload.get("to", "")
            subject = payload.get("subject", "")
            body = (f"Thanks for the email — I've received it and will follow up by EOD.\n\n"
                    f"— Sent by Hermes on behalf of Rohit.")
            ok = ei.send_email(to, subject, body)
            result = {"ok": ok, "code": 0 if ok else 1, "out": f"sent reply to {to[:40]}",
                      "err": "" if ok else "send failed", "elapsed_s": round(time.time() - start, 1)}
        except Exception as e:
            result = {"ok": False, "code": -3, "out": "", "err": str(e)[:1000], "elapsed_s": 0}
    else:
        result = {"ok": True, "code": 0, "out": "noop", "err": "", "elapsed_s": 0}
    return result


def run_approved(notify: bool = True) -> dict:
    """Execute every approved, not-yet-run action. Returns summary."""
    lk = Path("/tmp/sentinel_gate.lock")
    if not lock(lk, 180):
        return {"ok": False, "message": "already running"}
    try:
        actions = _load()
        executed, failed = [], []
        for a in actions:
            if a.get("status") != "approved" or a.get("ran_at"):
                continue
            a["status"] = "running"
            _save(actions)
            try:
                result = _execute(a)
            except Exception as e:  # defensive
                result = {"ok": False, "err": str(e)[:500]}
            a["status"] = "done" if result.get("ok") else "failed"
            a["ran_at"] = now_iso()
            a["result"] = result
            (executed if result.get("ok") else failed).append(a["id"])
            _save(actions)
            append_jsonl(DATA / "sentinel.log.jsonl", {
                "event": "ran", "id": a["id"], "ok": result.get("ok"), "code": result.get("code"),
            })
            if notify:
                status = "✅" if result.get("ok") else "❌"
                tail = (result.get("out") or result.get("err") or "")[:500]
                send(f"{status} Executed <b>{a['summary']}</b> [#{a['id']}]\n<pre>{tail or '-'}</pre>",
                     chat_id=a.get("chat_id"))
        return {"ok": True, "message": f"{len(executed)} ran, {len(failed)} failed",
                "executed": executed, "failed": failed}
    finally:
        unlock(lk)


def list_actions(pending_only: bool = False) -> list[dict]:
    actions = _load()
    if pending_only:
        actions = [a for a in actions if a.get("status") == "pending"]
    return actions


def status() -> dict:
    acts = _load()
    counts = {}
    for a in acts:
        counts[a.get("status", "?")] = counts.get(a.get("status", "?"), 0) + 1
    rules = _load_rules()
    return {"actions": len(acts), "by_status": counts, "rules": len(rules)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sentinel approval gate")
    ap.add_argument("--propose", help="summary of the proposed action")
    ap.add_argument("--kind", default="shell", choices=["shell", "tg_send", "none"])
    ap.add_argument("--argv", help="shell argv (space separated) or JSON list")
    ap.add_argument("--text", help="text for tg_send")
    ap.add_argument("--no-gate", action="store_true", help="skip approval (require_approval=False)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--approve", metavar="ID")
    ap.add_argument("--deny", metavar="ID")
    ap.add_argument("--always", metavar="ID")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args(argv)

    if args.propose:
        if args.kind == "shell":
            try:
                payload = {"argv": json.loads(args.argv or "[]")}
            except Exception:
                payload = {"argv": (args.argv or "").split()}
        elif args.kind == "tg_send":
            payload = {"text": args.text or args.propose}
        else:
            payload = {}
        rec = propose(args.propose, kind=args.kind, payload=payload,
                      require_approval=not args.no_gate)
        print(json.dumps({"id": rec["id"], "status": rec["status"]}))
        return 0
    if args.approve:
        print(json.dumps(approve(args.approve)))
        return 0
    if args.deny:
        print(json.dumps(deny(args.deny)))
        return 0
    if args.always:
        print(json.dumps(always(args.always)))
        return 0
    if args.run:
        print(json.dumps(run_approved()))
        return 0
    if args.status:
        print(json.dumps(status()))
        return 0
    if args.list or args.pending:
        for a in list_actions(args.pending):
            print(f"#{a['id']} [{a.get('status')}] {a.get('kind')}: {a.get('summary')}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())