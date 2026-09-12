#!/usr/bin/env python3
"""quiet_threads.py — proactive re-engagement of dropped threads.

Scans the tracked threads (data/tg_inbox.jsonl) and the commitment store for
open items that have gone quiet (> 2 days without activity). For each, drafts a
nudge in Rohit's voice; the draft goes through the SENTINEL approval gate
(kind tg_send) so the human flicks approve/deny before anything is sent.

This is the "Instinct" follow-up superpower: threads you dropped get picked back
up before they die, without you being the paste-and-copy router.

CLI:
  python3 quiet_threads.py --run     # propose nudges (scheduler job, daily)
  python3 quiet_threads.py --preview # show what would be proposed
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from agent_kits import DATA, read_json, write_json, now_iso, send

import sentinel_gate

TG_INBOX = DATA / "tg_inbox.jsonl"
STALE_AFTER_DAYS = 2


def _commitments() -> list[dict]:
    from agent_kits import load_commitments
    return load_commitments()


def _threads() -> list[dict]:
    out = []
    if not TG_INBOX.exists():
        return out
    for line in TG_INBOX.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _group_by_thread(msgs: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for m in msgs:
        if not m.get("text"):
            continue
        key = m.get("thread") or m.get("chat_id") or "_chat"
        groups.setdefault(key, []).append(m)
    return groups


def find_quiet() -> list[dict]:
    """Return {commit, thread_hint, days_quiet} for stale open commitments."""
    now = datetime.now(timezone.utc)
    out = []
    for c in _commitments():
        if c.get("status") != "open":
            continue
        due = c.get("due") or ""
        last = c.get("updated") or c.get("created") or str(due)
        try:
            last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            last_dt = now
        days = (now - last_dt).total_seconds() / 86400
        if days >= STALE_AFTER_DAYS:
            out.append({
                "text": c.get("text") or c.get("id"),
                "id": c.get("id"),
                "days_quiet": round(days, 1),
                "due": due or None,
            })
    return out


def _draft(commit: dict) -> str:
    due = f" (due {commit['due']})" if commit.get("due") else ""
    return (f"👋 Following up on a thread I tracked for you: “{commit['text'][:120]}”"
            f"{due}. It's gone quiet {commit['days_quiet']} day(s). "
            f"Want me to send a nudge, file it done, or drop it?")


def _state() -> dict:
    return read_json(DATA / "quiet_threads_state.json", {"nudged": {}})


def propose_nudges(autosend: bool = False) -> dict:
    st = _state()
    nudges = []
    for q in find_quiet():
        ckey = f"c:{q['id']}"
        if st["nudged"].get(ckey):
            continue
        text = _draft(q)
        rec = sentinel_gate.propose(
            summary=f"quiet-thread nudge: {q['text'][:80]}",
            kind="tg_send",
            payload={"text": text},
            source="quiet_threads",
            require_approval=not autosend,
        )
        st["nudged"][ckey] = {"proposed": now_iso(), "action_id": rec["id"]}
        nudges.append({"id": q["id"], "action_id": rec["id"], "text": text})
    write_json(DATA / "quiet_threads_state.json", st)
    return {"ok": True, "proposed": nudges}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args(argv)
    if args.preview:
        for q in find_quiet():
            print(f"- [{q['days_quiet']}d] {q['text'][:100]}")
        print(f"({len(find_quiet())} quiet commit(s))")
    else:
        print(json.dumps(propose_nudges(autosend=args.yes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())