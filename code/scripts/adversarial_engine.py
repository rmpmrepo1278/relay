#!/usr/bin/env python3
"""adversarial_engine.py — The heckler of the Agent Parliament.

Responsibility: stress-test every proposed autonomous action before the
council commits. Votes NO when a target has a recent incident on record
(restarting/flapping services is risky), otherwise approves on evidence of
recurring failure. Also publishes a standing "risk watch" scan.

Scheduler: council vote             */9  * * * (with council_vote_tally at */5
             risk watch             0    */6 * *
"""
import json
import sys
from pathlib import Path

HERMES_HOME = Path("/home/rohit/.hermes")
sys.path.insert(0, str(HERMES_HOME / "scripts" / "lib"))
sys.path.insert(0, str(HERMES_HOME / "hermes-agent" / "scripts" / "lib"))


def _risk_watch():
    """Standing scan: surface historically incident-prone targets."""
    alerts = HERMES_HOME / "data" / "alerts_inbox.json"
    incidents = set()
    if alerts.exists():
        try:
            data = json.loads(alerts.read_text())
            for a in data if isinstance(data, list) else []:
                msg = str(a.get("message", ""))
                # crude: grab the last token of a message as a candidate target
                for tok in msg.lower().split():
                    if tok in ("container", "service", "mcp", "dns") and tok not in incidents:
                        incidents.add(tok)
        except Exception:
            pass
    return sorted(incidents)


def main(argv):
    import council_vote
    if "--vote-council" in argv or "--vote" in argv:
        dry = "--dry-run" in argv
        cast = council_vote.cast_vote("adversarial_engine", dry=dry)
        if dry:
            print("[adversarial_engine] would-cast: " + "; ".join(f"{pid}={v}" for pid, v in cast) or "no open proposals")
        else:
            print("[adversarial_engine] cast " + "; ".join(f"{pid}={v}" for pid, v in cast) or "no votes needed")
        return 0
    watch = _risk_watch()
    if watch:
        print(f"⚠ adversarial_engine risk watch: {', '.join(watch)}")
    else:
        print("adversarial_engine: risk watch clear")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
