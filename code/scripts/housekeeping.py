#!/usr/bin/env python3
"""housekeeping.py — rotate unbounded jsonl logs and prune temp state.

The agent-kit modules append to several .jsonl files that grow without bound
(tg_inbox, sentinel.log, routines.log, voice_inbox, agent_mailbox.log,
quiet state, etc.). This job keeps each under a cap and prunes sentinel
non-executable sprawl safely.

CLI:
  python3 housekeeping.py --run    # (scheduler job, daily)
  python3 housekeeping.py --check  # report sizes before trimming
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_kits import HERMES_HOME, DATA, STATE, trim_jsonl, now_iso, append_jsonl

_CAPS = {
    "tg_inbox.jsonl": 1000,
    "sentinel.log.jsonl": 2000,
    "routines.log.jsonl": 500,
    "voice_inbox.jsonl": 500,
    "agent_mailbox.log.jsonl": 500,
    "quiet_threads_state.json": 200,
    "commitment_smart.json": 200,
    # unbounded growth audit (2026-09-12): episodic_memory 15k rows / 3.2M,
    # mind_insights 14k rows / 2.1M. Cap the raw files (consumers only see
    # the tail anyway); the dedup/reflection jobs materialise pointers, not
    # the raw text, so holding the newest rows is safe.
    "episodic_memory.tsv": 20000,
    "mind_insights.jsonl": 10000,
}

# daily_digest_*.md — keep the newest N by filename date
_KEEP_DAILY_DIGESTS = 45


def logs_todo(cap: dict | None = None) -> list[tuple[Path, int]]:
    cap = cap or _CAPS
    out = []
    for name, max_lines in cap.items():
        p = DATA / name
        if not p.exists():
            continue
        try:
            count = len(p.read_text().splitlines())
        except OSError:
            continue
        if count > max_lines:
            out.append((p, count))
    return out


def prune_daily_digests(keep: int = _KEEP_DAILY_DIGESTS) -> list[dict]:
    """Remove the oldest daily_digest_*.md past the cap (70 → 45)."""
    try:
        files = sorted(DATA.glob("daily_digest_*.md"))
    except OSError:
        return []
    removed = []
    for p in files[:-keep]:
        try:
            p.unlink()
            removed.append({"file": p.name})
        except OSError:
            continue
    return removed


def run() -> dict:
    trimmed = []
    for p, count in logs_todo():
        cap = _CAPS[p.name]
        ok = trim_jsonl(p, cap)
        trimmed.append({"file": p.name, "was": count, "kept": min(cap, count), "ok": ok})
    pruned = prune_daily_digests()
    append_jsonl(DATA / "housekeeping.log.jsonl", {
        "ts": now_iso(), "trimmed": len(trimmed), "digests_pruned": len(pruned),
    })
    return {"ok": True, "trimmed": trimmed, "digests_pruned": pruned}


def check() -> list[dict]:
    return [{"file": p.name, "lines": n} for p, n in logs_todo()]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.check:
        for r in check():
            print(f"{r['file']}: {r['lines']} lines (over cap)")
        print("ok" if not check() else "trim needed")
    else:
        r = run()
        for t in r["trimmed"]:
            print(f"{t['file']}: {t['was']} -> {t['kept']}")
        for d in r["digests_pruned"]:
            print(f"pruned digest: {d['file']}")
        if not r["trimmed"] and not r["digests_pruned"]:
            print("nothing to trim")
    return 0


if __name__ == "__main__":
    sys.exit(main())