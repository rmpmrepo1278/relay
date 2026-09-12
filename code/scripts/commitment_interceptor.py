#!/usr/bin/env python3
"""
commitment_interceptor.py — Auto-extract commitments from Hermes's outgoing messages.

This sits between Hermes's response generation and Telegram delivery.
Before a message is sent, this module:

1. Scans the message for commitment language ("I'll do X", "I'll deliver Y in Z minutes")
2. If commitments found, registers them in the commitment tracker
3. Logs the commitment for monitoring

This ensures that every promise Hermes makes is automatically tracked.

Usage:
    # Before sending a message to Telegram:
    python3 commitment_interceptor.py scan "<message_text>"

    # Returns JSON with extracted commitments
    # If commitments found, they are auto-registered in the tracker

Integration:
    This should be called by the gateway/telegram.py send path
    or by the proactive orchestrator before sending.
"""

from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
sys.path.insert(0, str(HERMES_HOME / "scripts"))

from commitment_tracker import extract_commitments, add_commitment


def scan_message(message: str, source: str = "telegram") -> dict:
    """
    Scan a message for commitments and auto-register them.

    Returns:
        {
            "has_commitments": bool,
            "commitments": [...],
            "message": str,  # original message
            "warning": str or None,  # warning if commitments detected
        }
    """
    extracted = extract_commitments(message)

    if not extracted:
        return {
            "has_commitments": False,
            "commitments": [],
            "message": message,
            "warning": None,
        }

    registered = []
    for ext in extracted:
        c = add_commitment(
            text=ext["text"],
            deadline=ext.get("deadline"),
            source=source,
            context=ext.get("source_text", "")[:100],
        )
        registered.append(c)

    # Build a warning if deadlines are tight
    warning = None
    short_deadlines = [c for c in registered if c.get("deadline")]
    if short_deadlines:
        warning = f"⚠️ Registered {len(registered)} commitment(s) with deadlines. Will track automatically."

    return {
        "has_commitments": True,
        "commitments": registered,
        "message": message,
        "warning": warning,
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: commitment_interceptor.py scan <message>")
        sys.exit(1)

    command = sys.argv[1]
    message = " ".join(sys.argv[2:])

    if command == "scan":
        result = scan_message(message)
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
