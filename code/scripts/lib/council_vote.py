#!/usr/bin/env python3
"""council_vote.py — shared vote-casting library for Agent Parliament members.

Each council member calls cast_vote(member, votes_file) to record a reasoned
ballot on any open proposal. Votes are evidence-based, not random, and a
member may only vote once per proposal (idempotent).
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path("/home/rohit/.hermes")
DB = HERMES_HOME / "data" / "unified_memory.db"
VOTES_FILE = HERMES_HOME / "state" / "decision_votes.json"

VALID = ("yes", "no", "abstain-yes", "abstain-no")


def _load_votes():
    if VOTES_FILE.exists():
        try:
            data = json.loads(VOTES_FILE.read_text())
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _save_votes(v):
    VOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    VOTES_FILE.write_text(json.dumps(v, indent=2))


def _recent_failures(gene, target, hours=24):
    """Number of recent failures for a gene+target (drives evidence)."""
    try:
        c = sqlite3.connect(DB)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        row = c.execute(
            "SELECT COUNT(*) FROM outcomes WHERE gene_id=? AND target=? "
            "AND outcome='fail' AND timestamp > ?",
            (gene, target, cutoff),
        ).fetchone()
        c.close()
        return row[0] if row else 0
    except Exception:
        return 0


def _recent_success_signal(action_key):
    """Did a prior fix for this service succeed (self_correction evidence)?"""
    try:
        c = sqlite3.connect(DB)
        row = c.execute(
            "SELECT COUNT(*) FROM outcomes WHERE outcome IN ('success','resolved') "
            "AND (notes LIKE ? OR target=(SELECT target FROM outcomes WHERE notes LIKE ? LIMIT 1) )",
            (f"%{action_key}%", f"%{action_key}%"),
        ).fetchone()
        c.close()
        return (row[0] if row else 0) > 0
    except Exception:
        return False


def _adb_recent_incident(target):
    """adversarial_engine: does this service have a recent escalation on record?"""
    try:
        alerts = HERMES_HOME / "data" / "alerts_inbox.jsonl"
        if alerts.exists():
            raw = alerts.read_text(errors="ignore").strip()
            data = json.loads(raw) if raw else []
            for a in data if isinstance(data, list) else []:
                if target.lower() in str(a.get("message", "")).lower():
                    return True
        return False
    except Exception:
        return False


def cast_vote(member, votes_file=None, dry=False):
    """Cast one ballot per open proposal for this member. Returns list of (pid, vote)."""
    fp = Path(votes_file) if votes_file else VOTES_FILE
    votes = _load_votes()
    if not isinstance(votes, dict):
        votes = {}
    cast = []
    for pid, prop in votes.items():
        if not isinstance(prop, dict):
            continue
        # skip finalized proposals (already tallied) and members who already voted
        if prop.get("status") in ("completed", "rejected"):
            continue
        if member in prop.get("votes", {}):
            continue
        action_key = prop.get("action_key", "")
        gene = prop.get("gene", "")
        target = prop.get("target", "")
        failures = prop.get("failures", 0)

        vote = _decide(member, action_key, gene, target, failures)
        if dry:
            cast.append((pid, f"would-vote:{vote}"))
            continue
        prop.setdefault("votes", {})[member] = vote
        cast.append((pid, vote))
    if not dry:
        _save_votes(votes)
    return cast


def _decide(member, action_key, gene, target, failures):
    """Evidence-based decision per member persona."""
    if member == "adversarial_engine":
        # Risk-averse: veto if target had a recent incident, else approve
        if _adb_recent_incident(target):
            return "no"
        return "yes" if failures >= 2 else "abstain-yes"

    if member == "self_correction":
        # Only approve if a prior fix of this kind succeeded
        return "yes" if _recent_success_signal(action_key) or failures >= 3 else "abstain-no"

    if member == "learning_integrator":
        # Recurring pattern (>=2) means it's worth acting on
        return "yes" if failures >= 2 else "abstain-yes"

    if member == "predictive_signals":
        # Approve if trend is clearly failing (degrades with each failure)
        return "yes" if failures >= 2 else "abstain-yes"

    if member == "insight_engine":
        # Approve by default; it's the broad synthesizer
        return "yes"
    return "abstain-yes"


def main(argv):
    args = [a for a in argv]
    member = None
    votes_file = None
    dry = "--dry-run" in args
    for i, a in enumerate(args):
        if a == "--vote-council":
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                member = args[i + 1]
        elif a.startswith("--votes-file="):
            votes_file = a.split("=", 1)[1]
    if not member:
        seen = [x for x in ["learning_integrator","insight_engine","adversarial_engine",
                            "predictive_signals","self_correction"] if x in args]
        member = seen[0] if seen else None
    if not member:
        print("usage: council_vote.py --vote-council <member> [--dry-run]")
        return 2
    cast = cast_vote(member, votes_file=votes_file, dry=dry)
    if dry:
        print(f"[{member}] would-cast: " + "; ".join(f"{pid}={v}" for pid, v in cast) or "no open proposals")
    else:
        print(f"[{member}] cast " + "; ".join(f"{pid}={v}" for pid, v in cast) or "no votes needed")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
