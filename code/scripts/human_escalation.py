#!/usr/bin/env python3
"""
human_escalation.py — Human escalation budget for low-confidence decisions.

When proactive engine confidence is below threshold, ask human via Telegram
instead of guessing. Tracks escalation budget to avoid spam.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
DATA_DIR = HERMES_HOME / "data"
ESCALATION_FILE = DATA_DIR / "escalation_budget.json"
ESCALATION_LOG = DATA_DIR / "escalation_log.jsonl"

sys.path.insert(0, str(HERMES_HOME / "scripts"))
try:
    from decision_ledger import record as ledger_record, resolve as ledger_resolve
except ImportError:
    ledger_record = None
    ledger_resolve = None


# Budget config
DEFAULT_BUDGET = {
    "max_per_day": 3,
    "max_per_week": 10,
    "cooldown_minutes": 60,
    "confidence_threshold": 0.6,  # Below this -> escalate
}


def _load_budget() -> dict:
    if ESCALATION_FILE.exists():
        try:
            return json.loads(ESCALATION_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "daily_count": 0,
        "weekly_count": 0,
        "last_escalation": None,
        "last_reset_day": datetime.now(timezone.utc).date().isoformat(),
        "last_reset_week": datetime.now(timezone.utc).isocalendar()[1],
    }


def _save_budget(budget: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ESCALATION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(budget, indent=2, default=str))
    os.replace(tmp, ESCALATION_FILE)


def _check_budget(budget: dict) -> tuple[bool, str]:
    """Check if we can escalate now. Returns (allowed, reason)."""
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    this_week = now.isocalendar()[1]
    
    # Reset daily counter
    if budget.get("last_reset_day") != today:
        budget["daily_count"] = 0
        budget["last_reset_day"] = today
    
    # Reset weekly counter
    if budget.get("last_reset_week") != this_week:
        budget["weekly_count"] = 0
        budget["last_reset_week"] = this_week
    
    # Check daily limit
    if budget["daily_count"] >= DEFAULT_BUDGET["max_per_day"]:
        return False, f"daily limit reached ({DEFAULT_BUDGET['max_per_day']})"
    
    # Check weekly limit
    if budget["weekly_count"] >= DEFAULT_BUDGET["max_per_week"]:
        return False, f"weekly limit reached ({DEFAULT_BUDGET['max_per_week']})"
    
    # Check cooldown
    last = budget.get("last_escalation")
    if last:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        if (now - last_dt).total_seconds() < DEFAULT_BUDGET["cooldown_minutes"] * 60:
            return False, f"cooldown active ({DEFAULT_BUDGET['cooldown_minutes']} min)"
    
    return True, "budget ok"


def should_escalate(confidence: float, action_context: dict) -> tuple[bool, str]:
    """Determine if we should escalate to human."""
    if confidence >= DEFAULT_BUDGET["confidence_threshold"]:
        return False, "confidence above threshold"
    
    budget = _load_budget()
    allowed, reason = _check_budget(budget)
    if not allowed:
        return False, reason
    
    return True, f"confidence {confidence:.2f} below threshold {DEFAULT_BUDGET['confidence_threshold']}"


def escalate_to_human(action_context: dict, confidence: float, reason: str) -> dict:
    """Send escalation to human via Telegram."""
    budget = _load_budget()
    allowed, budget_reason = _check_budget(budget)
    if not allowed:
        return {"escalated": False, "reason": budget_reason}
    
    # Format message
    msg = (
        f"🤔 *Hermes needs guidance*\n\n"
        f"*Action:* {action_context.get('action', 'unknown')}\n"
        f"*Target:* {action_context.get('target', 'N/A')}\n"
        f"*Rationale:* {action_context.get('rationale', 'N/A')}\n"
        f"*Confidence:* {confidence:.0%}\n"
        f"*Reason:* {reason}\n\n"
        f"*Options:*\n"
        f"1. ✅ Approve — proceed as planned\n"
        f"2. ❌ Reject — skip this action\n"
        f"3. 🔧 Modify — suggest alternative\n\n"
        f"Reply with number or text."
    )
    
    # Send via Telegram
    try:
        from send_telegram import send_to_telegram
        send_to_telegram(msg)
        telegram_sent = True
    except Exception as e:
        telegram_sent = False
        msg += f"\n\n⚠️ Telegram send failed: {e}"
    
    # Update budget
    now = datetime.now(timezone.utc).isoformat()
    budget["daily_count"] += 1
    budget["weekly_count"] += 1
    budget["last_escalation"] = now
    _save_budget(budget)
    
    # Log escalation
    ESCALATION_LOG.parent.mkdir(parents=True, exist_ok=True)
    log_entry = {
        "timestamp": now,
        "action_context": action_context,
        "confidence": confidence,
        "reason": reason,
        "telegram_sent": telegram_sent,
    }
    with open(ESCALATION_LOG, "a") as f:
        f.write(json.dumps(log_entry, default=str) + "\n")
    
    # Record in ledger
    if ledger_record:
        ledger_record(
            actor="human_escalation",
            action="escalate_to_human",
            rationale=f"Low confidence ({confidence:.0%}) for {action_context.get('action')}: {reason}",
            predicted_outcome="human_decision",
            target=action_context.get("target", ""),
            params={"confidence": confidence, "action": action_context.get("action")},
            triggered_by="low_confidence",
        )
    
    return {"escalated": True, "telegram_sent": telegram_sent, "message": msg}


def handle_human_response(response_text: str) -> dict:
    """Process human response to escalation. Returns decision."""
    response = response_text.strip().lower()
    
    # Simple parsing
    if any(w in response for w in ["1", "approve", "yes", "ok", "proceed", "go ahead"]):
        decision = "approve"
    elif any(w in response for w in ["2", "reject", "no", "skip", "cancel", "abort"]):
        decision = "reject"
    elif any(w in response for w in ["3", "modify", "change", "alternative", "instead"]):
        decision = "modify"
    else:
        decision = "unclear"
    
    # Log response
    now = datetime.now(timezone.utc).isoformat()
    log_entry = {
        "timestamp": now,
        "response": response_text,
        "decision": decision,
    }
    with open(ESCALATION_LOG, "a") as f:
        f.write(json.dumps(log_entry, default=str) + "\n")
    
    return {"decision": decision, "raw": response_text}


def get_escalation_stats() -> dict:
    """Get escalation statistics."""
    budget = _load_budget()
    if not ESCALATION_LOG.exists():
        return {"budget": budget, "total_escalations": 0}
    
    entries = []
    for line in ESCALATION_LOG.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    
    decisions = {}
    for e in entries:
        d = e.get("decision")
        if d:
            decisions[d] = decisions.get(d, 0) + 1
    
    return {
        "budget": budget,
        "total_escalations": len([e for e in entries if "action_context" in e]),
        "decisions": decisions,
        "recent": entries[-5:],
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check if should escalate (requires --confidence and --action)")
    parser.add_argument("--confidence", type=float, help="Confidence level (0-1)")
    parser.add_argument("--action", help="Action name")
    parser.add_argument("--target", default="", help="Action target")
    parser.add_argument("--rationale", default="", help="Action rationale")
    parser.add_argument("--escalate", action="store_true", help="Force escalation")
    parser.add_argument("--respond", help="Process human response")
    parser.add_argument("--stats", action="store_true", help="Show escalation stats")
    args = parser.parse_args()
    
    if args.check:
        ctx = {"action": args.action, "target": args.target, "rationale": args.rationale}
        should, reason = should_escalate(args.confidence, ctx)
        print(json.dumps({"should_escalate": should, "reason": reason}))
    elif args.escalate:
        ctx = {"action": args.action, "target": args.target, "rationale": args.rationale}
        result = escalate_to_human(ctx, args.confidence or 0.5, "manual escalation")
        print(json.dumps(result))
    elif args.respond:
        result = handle_human_response(args.respond)
        print(json.dumps(result))
    elif args.stats:
        print(json.dumps(get_escalation_stats(), indent=2, default=str))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()