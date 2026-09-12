#!/usr/bin/env python3
"""agent_mailbox.py — Hermes's own email presence (the "Instinct email" pattern).

Hermes gets a real address. Anything forwarded to it (order confirmations,
group-thread CCs, "please handle this") lands in the agent mailbox and is
processed:

  * forwarded order/shipment confirmation  -> propose an order-tracking action
  * commitments ("I'll send the deck")     -> auto-track via commitment_tracker
  * anything else                          -> logged to data/agent_mailbox.log.jsonl
    and surfaced in the next digest

Inbound is a drop folder of .eml/.txt files:
  ~/.hermes/agent_mailbox/in/
Processed files move to ~/.hermes/agent_mailbox/out/ with the date prefix.

Provisioning (pick one, set AGENT_MAILBOX_ADDR in ~/.hermes/.env):
  1. A dedicated Gmail+ Google account, OAuth via existing auth_gmail.py, that
     dumps new mail to the drop folder (see docs/agent-mailbox.md).
  2. A self-hosted catch-all (postfix on the homelab) piping into the folder.

CLI:
  python3 agent_mailbox.py --process        # handle everything new (scheduler job)
  python3 agent_mailbox.py --digest         # print/send a short digest
  python3 agent_mailbox.py --log            # show recent processed items
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from agent_kits import HERMES_HOME, DATA, read_json, write_json, append_jsonl, send, now_iso

import sentinel_gate

MB = HERMES_HOME / "agent_mailbox"
INBOX = MB / "in"
OUTBOX = MB / "out"

_ORDER_HINTS = ("order confirmation", "your order", "receipt", "invoice",
                "tracking number", "shipment", "shipped", "dispatch")
_COMMIT_HINTS = ("i'll send", "i will send", "i'll do", "i will do", "i'll get",
                 "i will get", "by friday", "by monday", "by tomorrow", "eod")


def _classify(text: str) -> str:
    low = text.lower()
    if any(h in low for h in _ORDER_HINTS):
        return "order"
    if any(h in low for h in _COMMIT_HINTS):
        return "commitment"
    return "other"


def _handle_file(p: Path) -> dict:
    try:
        text = p.read_text(errors="replace")
    except OSError as e:
        return {"file": p.name, "status": "error", "error": str(e)}
    kind = _classify(text)
    rec = {"file": p.name, "kind": kind, "ts": now_iso()}
    if kind == "order":
        sentinel_gate.propose(
            summary=f"agent-mailbox order item: {p.name}",
            kind="none", payload={}, source="agent_mailbox",
        )
        rec["action"] = "proposed-tracking"
    elif kind == "commitment":
        try:
            from commitment_tracker import add_commitment
            add_commitment(text[:300], source=f"mailbox:{p.name}")
            rec["commits_added"] = True
        except Exception:
            rec["commits_added"] = False
    else:
        rec["digest_candidate"] = True
    append_jsonl(DATA / "agent_mailbox.log.jsonl", rec)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    dst = OUTBOX / (now_iso()[:10] + "_" + p.name)
    try:
        p.replace(dst)
    except OSError:
        pass
    return rec


def process() -> dict:
    if not INBOX.exists():
        return {"ok": True, "processed": []}
    out = []
    for p in sorted(INBOX.iterdir()):
        if p.is_file():
            out.append(_handle_file(p))
    if out:
        send(f"📬 Agent mailbox: processed {len(out)} new item(s).")
    return {"ok": True, "processed": out}


def digest() -> str:
    if not (DATA / "agent_mailbox.log.jsonl").exists():
        return "📬 No mailbox activity yet. Provision AGENT_MAILBOX_ADDR (see docs/agent-mailbox.md)."
    lines = []
    for line in (DATA / "agent_mailbox.log.jsonl").read_text().splitlines()[-12:]:
        try:
            r = json.loads(line)
            lines.append(f"• {r.get('ts', '?')[:16]} [{r.get('kind', '?')}] {r.get('file', '?')}")
        except json.JSONDecodeError:
            continue
    return "📬 Recent mailbox activity:\n" + ("\n".join(lines) or "none")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--process", action="store_true")
    ap.add_argument("--digest", action="store_true")
    ap.add_argument("--log", action="store_true")
    args = ap.parse_args(argv)
    if args.process:
        print(json.dumps(process()))
    elif args.log:
        if (DATA / "agent_mailbox.log.jsonl").exists():
            print("\n".join((DATA / "agent_mailbox.log.jsonl").read_text().splitlines()[-15:]))
    else:
        print(digest())
    return 0


if __name__ == "__main__":
    sys.exit(main())