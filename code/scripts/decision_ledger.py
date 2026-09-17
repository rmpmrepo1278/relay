#!/usr/bin/env python3
"""
decision_ledger.py — Unified ledger for every autonomous action.

Every action Hermes takes on its own initiative gets a record: who acted,
what they did, WHY (rationale), what outcome was predicted, and — after
verification — what actually happened. This is the raw material for
demonstrating (and improving) real agency.

Records are append-only JSONL. Two-phase lifecycle:
  record()  -> open entry (predicted outcome)
  resolve() -> close entry with actual outcome + evidence

Usage:
    python3 decision_ledger.py record --actor hermes_mind --action restart --target paperless \
        --rationale "3 consecutive failures" --predicted success --params '{"tier": 1}'
    python3 decision_ledger.py resolve --id <uuid> --outcome success --evidence "container healthy"
    python3 decision_ledger.py stats
    python3 decision_ledger.py recent [--limit 20]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
LEDGER_FILE = HERMES_HOME / "data" / "decision_ledger.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(
    actor: str,
    action: str,
    rationale: str,
    predicted_outcome: str = "unknown",
    target: str = "",
    params: dict | None = None,
    triggered_by: str = "schedule",
) -> dict:
    """Open a ledger entry. Returns the entry (with id) for later resolve()."""
    entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": _now(),
        "actor": actor,
        "action": action,
        "target": target,
        "rationale": rationale,
        "predicted_outcome": predicted_outcome,
        "params": params or {},
        "triggered_by": triggered_by,
        "status": "open",
    }
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_FILE, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


def resolve(decision_id: str, outcome: str, evidence: str = "", actor: str = "") -> dict | None:
    """Close an open entry with the actual outcome + evidence."""
    lines = LEDGER_FILE.read_text().splitlines() if LEDGER_FILE.exists() else []
    target_idx = None
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("id") == decision_id and entry.get("status") == "open":
            entry["status"] = "resolved"
            entry["resolved_at"] = _now()
            entry["actual_outcome"] = outcome
            entry["evidence"] = evidence
            if actor:
                entry["resolved_by"] = actor
            lines[i] = json.dumps(entry, default=str)
            target_idx = i
            break
    if target_idx is None:
        return None
    with open(LEDGER_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")
    return json.loads(lines[target_idx])


def load(limit: int = 0, status: str = "") -> list[dict]:
    if not LEDGER_FILE.exists():
        return []
    entries = []
    for line in LEDGER_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if status and e.get("status") != status:
            continue
        entries.append(e)
    if limit > 0:
        entries = entries[-limit:]
    return entries


def stats() -> dict:
    entries = load()
    from collections import Counter
    by_status = Counter(e.get("status") for e in entries)
    by_actor = Counter(e.get("actor") for e in entries)
    by_trigger = Counter(e.get("triggered_by") for e in entries)
    resolved = [e for e in entries if e.get("status") == "resolved"]
    by_outcome = Counter(e.get("actual_outcome") for e in resolved)
    return {
        "total": len(entries),
        "open": by_status.get("open", 0),
        "resolved": by_status.get("resolved", 0),
        "by_actor": dict(by_actor),
        "by_trigger": dict(by_trigger),
        "by_outcome": dict(by_outcome),
    }


def _fmt(e: dict) -> str:
    outcome = e.get("actual_outcome") or e.get("predicted_outcome") or "?"
    return (f"  [{e.get('timestamp', '')[:19]}] {e.get('actor','?'):16s} "
            f"{e.get('action','?'):18s} {e.get('target',''):24s} "
            f"{e.get('status','?'):8s} outcome={outcome}\n"
            f"      why: {e.get('rationale','')[:100]}")


def main():
    parser = argparse.ArgumentParser(description="Decision ledger")
    sub = parser.add_subparsers(dest="command", required=True)

    p_r = sub.add_parser("record", help="Open a ledger entry")
    p_r.add_argument("--actor", required=True)
    p_r.add_argument("--action", required=True)
    p_r.add_argument("--rationale", required=True)
    p_r.add_argument("--predicted", default="unknown")
    p_r.add_argument("--target", default="")
    p_r.add_argument("--params", default="{}")
    p_r.add_argument("--triggered-by", default="schedule")

    p_v = sub.add_parser("resolve", help="Close an entry with outcome")
    p_v.add_argument("--id", required=True)
    p_v.add_argument("--outcome", required=True, choices=["success", "partial", "fail"])
    p_v.add_argument("--evidence", default="")
    p_v.add_argument("--actor", default="")

    p_s = sub.add_parser("stats", help="Aggregate stats")
    p_r2 = sub.add_parser("recent", help="Recent entries")
    p_r2.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    if args.command == "record":
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError:
            params = {}
        e = record(args.actor, args.action, args.rationale, args.predicted,
                   args.target, params, args.triggered_by)
        print(f"recorded {e['id']}")
    elif args.command == "resolve":
        r = resolve(args.id, args.outcome, args.evidence, args.actor)
        if r is None:
            print(f"no open entry with id {args.id}")
            sys.exit(1)
        print(f"resolved {args.id} -> {args.outcome}")
    elif args.command == "stats":
        s = stats()
        print(f"total={s['total']} open={s['open']} resolved={s['resolved']}")
        print(f"by_actor: {s['by_actor']}")
        print(f"by_trigger: {s['by_trigger']}")
        print(f"by_outcome: {s['by_outcome']}")
    elif args.command == "recent":
        for e in load(limit=args.limit):
            print(_fmt(e))


if __name__ == "__main__":
    main()
