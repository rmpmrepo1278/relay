#!/usr/bin/env python3
"""
Feedback Loop — Tracks which proactive suggestions Rohit acts on vs. ignores.

This closes the gap between "broadcasting" and "mindreading" by:
  1. Logging every proactive suggestion sent to Telegram
  2. Tracking Rohit's responses (or lack thereof)
  3. Adjusting future suggestion frequency based on engagement
  4. Deprioritizing suggestion types that are consistently ignored

Usage:
  python3 feedback_loop.py log <suggestion_type> <message_id>   # Log a suggestion
  python3 feedback_loop.py respond <message_id> <action>         # Record Rohit's response
  python3 feedback_loop.py report                                # Show engagement stats
  python3 feedback_loop.py adjust                                # Generate adjustment recommendations
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

DATA_FILE = Path.home() / ".hermes" / "data" / "feedback_loop.json"
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_DATA = {
    "suggestions": [],
    "responses": [],
    "stats": {
        "by_type": {},
        "by_time": {},
        "overall_accept_rate": 0.0,
    },
    "adjustments": {
        "suppress_types": [],      # Types with <10% accept rate
        "boost_types": [],         # Types with >50% accept rate
        "quiet_hours": [],         # Hours when Rohit never responds
    }
}


def load_data():
    try:
        return json.loads(DATA_FILE.read_text())
    except Exception:
        return dict(DEFAULT_DATA)


def save_data(data):
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(DATA_FILE)


def log_suggestion(suggestion_type, message_id, content=""):
    data = load_data()
    entry = {
        "id": f"{suggestion_type}_{message_id}_{datetime.now().strftime('%Y%m%d_%H%M')}",
        "type": suggestion_type,
        "message_id": message_id,
        "content": content[:200],
        "sent_at": datetime.now().isoformat(),
        "status": "pending",  # pending, accepted, ignored
    }
    data["suggestions"].append(entry)

    # Update type stats
    by_type = data["stats"]["by_type"]
    if suggestion_type not in by_type:
        by_type[suggestion_type] = {"sent": 0, "accepted": 0, "ignored": 0}
    by_type[suggestion_type]["sent"] += 1

    # Trim old entries (keep last 90 days)
    cutoff = (datetime.now() - timedelta(days=90)).isoformat()
    data["suggestions"] = [s for s in data["suggestions"] if s["sent_at"] > cutoff]

    save_data(data)
    print(f"Logged: {suggestion_type} suggestion (id={entry['id']})")


def record_response(message_id, action="accepted"):
    """Record that Rohit responded to or acted on a suggestion."""
    data = load_data()
    response = {
        "message_id": message_id,
        "action": action,  # accepted, dismissed, ignored
        "recorded_at": datetime.now().isoformat(),
    }
    data["responses"].append(response)

    # Find matching suggestion and update status
    for s in data["suggestions"]:
        if s["message_id"] == message_id:
            s["status"] = "accepted" if action in ("accepted", "acted") else "ignored"
            st = s["type"]
            if st in data["stats"]["by_type"]:
                data["stats"]["by_type"][st][s["status"]] += 1
            break

    save_data(data)
    print(f"Recorded: {action} for message {message_id}")


def generate_report():
    data = load_data()
    stats = data["stats"]["by_type"]

    print("=" * 60)
    print("📊 CoS Feedback Loop Report")
    print("=" * 60)
    print(f"Total suggestions sent: {len(data['suggestions'])}")
    print(f"Total responses recorded: {len(data['responses'])}")
    print()

    if not stats:
        print("No data yet. Start logging suggestions with: feedback_loop.py log <type> <msg_id>")
        return

    print("Engagement by type:")
    print(f"  {'Type':<25} {'Sent':>5} {'Accepted':>9} {'Ignored':>8} {'Rate':>7}")
    print("  " + "-" * 58)

    for stype, counts in sorted(stats.items(), key=lambda x: x[1]["sent"], reverse=True):
        sent = counts["sent"]
        accepted = counts.get("accepted", 0)
        ignored = counts.get("ignored", 0)
        pending = sent - accepted - ignored
        rate = (accepted / (accepted + ignored) * 100) if (accepted + ignored) > 0 else 0
        print(f"  {stype:<25} {sent:>5} {accepted:>9} {ignored:>8} {rate:>6.0f}%")
        if pending > 0:
            print(f"  {'':25} ({pending} pending)")

    # Calculate overall rate
    total_accepted = sum(c.get("accepted", 0) for c in stats.values())
    total_responded = sum(c.get("accepted", 0) + c.get("ignored", 0) for c in stats.values())
    if total_responded > 0:
        overall = total_accepted / total_responded * 100
        print(f"\nOverall accept rate: {overall:.0f}%")

    # Recent activity
    recent = [s for s in data["suggestions"][-10:]]
    if recent:
        print(f"\nLast {len(recent)} suggestions:")
        for s in recent:
            status_emoji = {"pending": "⏳", "accepted": "✅", "ignored": "❌"}.get(s["status"], "?")
            print(f"  {status_emoji} [{s['type']}] {s['content'][:60]}...")


def generate_adjustments():
    """Analyze patterns and recommend adjustments to proactive behavior."""
    data = load_data()
    stats = data["stats"]["by_type"]
    adjustments = {"suppress": [], "boost": [], "recommendations": []}

    for stype, counts in stats.items():
        responded = counts.get("accepted", 0) + counts.get("ignored", 0)
        if responded < 3:
            continue  # Not enough data
        rate = counts.get("accepted", 0) / responded
        if rate < 0.1:
            adjustments["suppress"].append(stype)
        elif rate > 0.5:
            adjustments["boost"].append(stype)

    print("=" * 60)
    print("🎯 Adjustment Recommendations")
    print("=" * 60)

    if adjustments["suppress"]:
        print("\n⛔ Consider reducing/suppressing these (low engagement):")
        for t in adjustments["suppress"]:
            print(f"  - {t}")

    if adjustments["boost"]:
        print("\n✅ These are well-received — can increase frequency:")
        for t in adjustments["boost"]:
            print(f"  - {t}")

    if not adjustments["suppress"] and not adjustments["boost"]:
        print("\nNot enough response data yet. Need at least 3 responses per type.")

    print("\n📋 General recommendations:")
    print("  1. If daily_audit is ignored >50%, reduce to weekly")
    print("  2. If career_scan is ignored, Rohit may not be job-searching right now")
    print("  3. If wellness checks are ignored, reduce frequency or change tone")
    print("  4. Track time-of-day patterns — morning briefings may get more engagement")

    return adjustments


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: feedback_loop.py <log|respond|report|adjust> [args]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "log" and len(sys.argv) >= 4:
        log_suggestion(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]) if len(sys.argv) > 4 else "")
    elif cmd == "respond" and len(sys.argv) >= 4:
        record_response(sys.argv[2], sys.argv[3])
    elif cmd == "report":
        generate_report()
    elif cmd == "adjust":
        generate_adjustments()
    else:
        print("Usage:")
        print("  feedback_loop.py log <type> <msg_id> [content]")
        print("  feedback_loop.py respond <msg_id> <accepted|dismissed|ignored>")
        print("  feedback_loop.py report")
        print("  feedback_loop.py adjust")


# ── Adapters for the unified decision ledger ───────────────────────────
# mind_loop.py calls record_action() / load_feedback() / check_action_outcomes().
# These bridge the old feedback loop into the decision ledger so outcomes are
# tracked and resolved in one place.

def record_action(action_type: str, content: str = "", **kwargs):
    """Record an action in the decision ledger (proactive suggestion or command)."""
    try:
        sys.path.insert(0, str(Path.home() / ".hermes" / "scripts"))
        from decision_ledger import record as _record
        _record(
            actor="mind_loop",
            action=action_type,
            rationale=(content or action_type)[:160],
            predicted_outcome="informational" if action_type == "proactive_message" else "success",
            target="",
            params={"content": (content or "")[:200]},
            triggered_by="mind_cycle",
        )
    except Exception:
        pass
    # Keep legacy file compatibility
    try:
        log_suggestion(action_type, "", content)
    except Exception:
        pass


def load_feedback() -> list:
    """Return recent feedback entries (from ledger)."""
    try:
        sys.path.insert(0, str(Path.home() / ".hermes" / "scripts"))
        from decision_ledger import load as _load
        return _load(limit=50)
    except Exception:
        return []


def check_action_outcomes(feedback: list) -> list:
    """Check open ledger actions for resolvable outcomes (best-effort)."""
    resolved = []
    for entry in feedback:
        if entry.get("status") != "open":
            continue
        if entry.get("actor") != "mind_loop":
            continue
        action = entry.get("action", "")
        if action == "run_command":
            resolved.append({"id": entry["id"], "outcome": "pending"})
    return resolved
