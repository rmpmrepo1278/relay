#!/usr/bin/env python3
"""
capsule_tracker.py — Records fix outcomes for gene success-rate learning.

Called by autonomous_fixer.py after each fix attempt. Records:
  - gene_id (which strategy was used)
  - target (what was fixed)
  - outcome (success/fail/partial)
  - signals (what triggered the fix)
  - notes (details)

Also provides query interface for gene_engine.py to compute success rates.

Usage:
  python3 capsule_tracker.py record --gene gene_container_crash --target paperless --outcome success --notes "..."
  python3 capsule_tracker.py query --gene gene_container_crash
  python3 capsule_tracker.py stats
"""

from __future__ import annotations

import subprocess
import json
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
CAPSULES_DIR = HERMES_HOME / "capsules"
OUTCOMES_FILE = CAPSULES_DIR / "outcomes.jsonl"
CAPSULE_FILE = OUTCOMES_FILE  # alias for capsule_verify.py compatibility


def record(gene_id: str, target: str, outcome: str, signals: list[str] | None = None,
           blast_radius: dict | None = None, notes: str = "", source: str = "autonomous_fixer"):
    """Record a fix outcome in the capsule log."""
    CAPSULES_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gene_id": gene_id,
        "target": target,
        "outcome": outcome,
        "signals": signals or [],
        "blast_radius": blast_radius or {},
        "notes": notes,
        "source": source,
    }
    with open(OUTCOMES_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def load_all() -> list[dict]:
    if not OUTCOMES_FILE.exists():
        return []
    items = []
    for line in OUTCOMES_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return items


def query(gene_id: str | None = None, target: str | None = None) -> list[dict]:
    records = load_all()
    if gene_id:
        records = [r for r in records if r.get("gene_id") == gene_id]
    if target:
        records = [r for r in records if r.get("target") == target]
    return records


def stats():
    records = load_all()
    if not records:
        print("No capsule outcomes recorded yet.")
        return

    by_gene: dict[str, list[dict]] = {}
    for r in records:
        gid = r.get("gene_id", "unknown")
        by_gene.setdefault(gid, []).append(r)

    print(f"\n{'Gene':<30} {'Success':>8} {'Fail':>6} {'Partial':>8} {'Rate':>8}")
    print("-" * 70)
    for gene_id, recs in sorted(by_gene.items()):
        s = sum(1 for r in recs if r.get("outcome") == "success")
        f = sum(1 for r in recs if r.get("outcome") == "fail")
        p = sum(1 for r in recs if r.get("outcome") == "partial")
        total = len(recs)
        rate = s / total if total > 0 else 0
        print(f"  {gene_id:<28} {s:>8} {f:>6} {p:>8} {rate:>7.0%}")


def load_capsules(gene_id: str | None = None, limit: int = 0) -> list[dict]:
    """Load Capsule records, optionally filtered by Gene ID."""
    if not CAPSULE_FILE.exists():
        return []
    capsules = []
    for line in CAPSULE_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            c = json.loads(line)
            if gene_id is None or c.get("gene_id") == gene_id:
                capsules.append(c)
        except json.JSONDecodeError:
            continue
    if limit > 0:
        capsules = capsules[-limit:]
    return capsules


def check_target_health(target: str) -> str | None:
    """Best-effort re-check of a target's health. Returns 'success'|'fail'|None."""
    # Try docker inspect for container targets
    try:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", target],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode == 0 and out.stdout.strip():
            st = out.stdout.strip()
            if st in ("healthy", "running", "up"):
                return "success"
            if st in ("unhealthy", "exited", "dead", "paused", "restarting"):
                return "fail"
            return None
    except (subprocess.TimeoutExpired, OSError):
        pass
    # Try docker ps --filter name
    try:
        out = subprocess.run(["docker", "ps", "-q", "--filter", f"name={target}"],
                             capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            return "success"
        return "fail"
    except (subprocess.TimeoutExpired, OSError):
        return None


def verify(target: str, gene_id: str = "", outcome: str = "", mark: str | None = None) -> dict | None:
    """Re-check target health and append verification to the latest matching record."""
    lines = CAPSULE_FILE.read_text().splitlines() if CAPSULE_FILE.exists() else []
    target_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if not lines[i].strip():
            continue
        try:
            c = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if c.get("target") == target:
            if gene_id and c.get("gene_id") != gene_id:
                continue
            if outcome and c.get("outcome") != outcome:
                continue
            if c.get("verified") is True:
                return None  # already verified
            target_idx = i
            break
    if target_idx is None:
        return None

    actual = mark or check_target_health(target)
    if actual is None:
        return None
    entry = json.loads(lines[target_idx])
    entry["verified"] = True
    entry["verified_at"] = datetime.now(timezone.utc).isoformat()
    entry["actual_outcome"] = actual
    lines[target_idx] = json.dumps(entry, default=str)
    with open(CAPSULE_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")
    return entry


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Capsule outcome tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="Record a fix outcome")
    rec.add_argument("--gene", required=True)
    rec.add_argument("--target", required=True)
    rec.add_argument("--outcome", required=True, choices=["success", "fail", "partial", "dry_run"])
    rec.add_argument("--signals", nargs="*", default=[])
    rec.add_argument("--notes", default="")
    rec.add_argument("--source", default="autonomous_fixer")

    qry = sub.add_parser("query", help="Query outcomes")
    qry.add_argument("--gene", default=None)
    qry.add_argument("--target", default=None)
    qry.add_argument("--json", action="store_true")

    statsp = sub.add_parser("stats", help="Show success rate statistics")

    args = parser.parse_args()

    if args.command == "record":
        entry = record(args.gene, args.target, args.outcome, args.signals, notes=args.notes, source=args.source)
        print(json.dumps(entry, indent=2))
    elif args.command == "query":
        results = query(args.gene, args.target)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            for r in results:
                print(f"  [{r['timestamp']}] {r['gene_id']} -> {r['target']}: {r['outcome']}")
    elif args.command == "stats":
        stats()
