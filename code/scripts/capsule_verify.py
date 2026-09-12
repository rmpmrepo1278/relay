#!/usr/bin/env python3
"""
capsule_verify.py — Periodic capsule outcome verification.

Closes the "did it actually help?" loop: for capsule records recorded in the
last N hours that haven't been verified yet, re-check the target's health and
append verified:true/false. Only re-checks when enough time has passed for the
fix to settle (min_age_minutes), avoiding false "failed" on slow containers.

Scheduled: every 15 minutes via hermes_scheduler.py.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
sys.path.insert(0, str(HERMES_HOME / "scripts"))
from capsule_tracker import load_capsules, verify, check_target_health

LOOKBACK_HOURS = 24
MIN_AGE_MINUTES = 10


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    min_age = now - timedelta(minutes=MIN_AGE_MINUTES)

    candidates = 0
    verified = 0
    for c in load_capsules():
        ts = c.get("timestamp", "")
        try:
            created = datetime.fromisoformat(ts)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if c.get("verified"):
            continue
        if created < cutoff:
            continue  # too old to bother re-checking
        if created > min_age:
            continue  # too fresh — fix hasn't settled yet
        if c.get("target") in ("unknown", ""):
            continue
        candidates += 1
        entry = verify(
            target=c["target"],
            gene_id=c.get("gene_id", ""),
            outcome=c.get("outcome", ""),
        )
        if entry:
            verified += 1

    print(f"capsule_verify: {candidates} candidates, {verified} verified")


if __name__ == "__main__":
    main()
