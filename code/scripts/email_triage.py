#!/usr/bin/env python3
"""email_triage.py — Email Triage Autopilot (watch → classify → propose → act).

Runs every ~2h (outside the nightly outage window) and:
  1. Fetches recent unseen Gmail messages (last LOOKBACK_HOURS).
  2. Classifies each into actionable/career/security/meeting/informational.
  3. Proposes ONE sentinel-gated auto-reply for the highest-priority item
     (only when not already proposed for that message).
  4. Logs the decision to email_triage.log.jsonl.

Approved actions are executed by sentinel_gate._execute kind="emailTriage",
which calls email_intelligence.send_email to send an acknowledgement reply.

CLI:
  python3 email_triage.py            # run the triage cycle
  python3 email_triage.py --digest   # print/send a summary of today's triage
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from agent_kits import HERMES_HOME, DATA, read_json, write_json, append_jsonl, now_iso

_SEEN_CACHE = HERMES_HOME / "data" / "email_ids_seen.json"
_PROPOSED_CACHE = HERMES_HOME / "data" / "email_triage_proposed.json"
_LOOKBACK_HOURS = 4
_PRIORITY = ["actionable", "security", "career", "meeting", "financial", "informational"]
# Only these categories are worth an auto-reply acknowledgment. Informational
# (shipment updates, newsletters, promotions) is logged but never auto-replied.
_REPLY_WORTHY = {"actionable", "security", "career"}


def _esc(t: str) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _load_json(p: Path, default):
    return read_json(p, default)


def _save_json(p: Path, data):
    write_json(p, data)


def _get_service():
    """Lazy-import the Gmail service (avoids import failure when deps missing)."""
    try:
        import sys as _s
        _s.path.insert(0, str(HERMES_HOME / "scripts"))
        from email_intelligence import get_gmail_service
        return get_gmail_service()
    except Exception:
        return None


def _categorize(subject: str, snippet: str) -> str:
    low = (subject + " " + snippet).lower()
    for cat in ["actionable", "security", "career", "meeting", "financial"]:
        keywords = {
            "actionable": ["invoice", "bill", "action required", "deadline", "rsvp", "confirm", "sign"],
            "security": ["password reset", "suspicious", "security alert", "2fa", "new sign-in"],
            "career": ["interview", "recruiter", "hiring", "opportunity", "resume"],
            "meeting": ["meeting", "calendar", "invite", "zoom", "teams"],
            "financial": ["receipt", "statement", "charged", "refund"],
        }.get(cat, [])
        if any(k in low for k in keywords):
            return cat
    return "informational"


def _already_proposed(msg_id: str) -> bool:
    prop = _load_json(_PROPOSED_CACHE, {"ids": []})
    return msg_id in prop.get("ids", [])


def _mark_proposed(msg_id: str):
    prop = _load_json(_PROPOSED_CACHE, {"ids": []})
    ids = prop.get("ids", [])
    ids.append(msg_id)
    # keep last 200
    if len(ids) > 200:
        ids = ids[-200:]
    _save_json(_PROPOSED_CACHE, {"ids": ids, "last": now_iso()})


def run() -> dict:
    """Full triage cycle. Returns summary dict."""
    # network guard
    try:
        import sys as _s
        _s.path.insert(0, str(HERMES_HOME / "scripts" / "lib"))
        from network_guard import guard
        skip, reason = guard()
        if skip:
            return {"ok": True, "skipped": reason, "proposed": 0}
    except Exception:
        pass

    svc = _get_service()
    if svc is None:
        return {"ok": False, "error": "gmail service unavailable"}

    seen_ids = _load_json(_SEEN_CACHE, {"ids": []})
    if not isinstance(seen_ids, dict):
        seen_ids = {"ids": list(seen_ids) if isinstance(seen_ids, list) else []}
    seen_set = set(seen_ids.get("ids", []))

    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=_LOOKBACK_HOURS)).isoformat()
        results = svc.users().messages().list(
            userId="me", q=f"after:{cutoff[:10]} newer_than:{_LOOKBACK_HOURS}h",
            maxResults=20).execute()
        messages = results.get("messages", [])
    except Exception as e:
        return {"ok": False, "error": f"gmail list failed: {e}"}

    candidates = []
    new_count = 0
    for m in messages:
        mid = m.get("id")
        if not mid or mid in seen_set:
            continue
        new_count += 1
        try:
            msg = svc.users().messages().get(userId="me", id=mid, format="metadata",
                                             metadataHeaders=["Subject", "From"]).execute()
        except Exception:
            continue
        hdrs = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        subject = hdrs.get("Subject", "(no subject)")
        sender = hdrs.get("From", "")
        snippet = msg.get("snippet", "")
        cat = _categorize(subject, snippet)
        candidates.append({
            "msg_id": mid, "subject": subject, "from": sender,
            "snippet": snippet, "category": cat,
        })

    # update seen
    new_ids = seen_ids.get("ids", []) + [c["msg_id"] for c in candidates]
    if len(new_ids) > 500:
        new_ids = new_ids[-500:]
    _save_json(_SEEN_CACHE, {"ids": new_ids, "last": now_iso()})

    if not candidates:
        append_jsonl(DATA / "email_triage.log.jsonl",
                     {"ts": now_iso(), "new": new_count, "proposed": 0})
        return {"ok": True, "new": new_count, "proposed": 0}

    # pick best unproposed candidate by priority rank among reply-worthy cats
    worthy = [c for c in candidates if c["category"] in _REPLY_WORTHY]
    if not worthy:
        append_jsonl(DATA / "email_triage.log.jsonl",
                     {"ts": now_iso(), "new": new_count, "proposed": 0, "reason": "no reply-worthy"})
        return {"ok": True, "new": new_count, "proposed": 0}
    worthy.sort(key=lambda c: _PRIORITY.index(c["category"]))
    proposed_id = None
    for c in candidates:
        if _already_proposed(c["msg_id"]):
            continue
        # propose to sentinel
        try:
            import sys as _s
            _s.path.insert(0, str(HERMES_HOME / "scripts"))
            import sentinel_gate
            rec = sentinel_gate.propose(
                summary=f"Auto-reply to <b>{c['subject'][:60]}</b> from {_esc(c['from'][:30])} "
                        f"[{_esc(c['category'])}]",
                kind="emailTriage",
                payload={"msg_id": c["msg_id"], "to": c["from"],
                         "subject": f"Re: {c['subject'][:80]}",
                         "snippet": c["snippet"][:200]},
                source="email_triage",
            )
            _mark_proposed(c["msg_id"])
            proposed_id = rec.get("id")
            break
        except Exception:
            continue

    append_jsonl(DATA / "email_triage.log.jsonl", {
        "ts": now_iso(), "new": new_count, "proposed": 1 if proposed_id else 0,
        "proposed_id": proposed_id,
    })
    return {"ok": True, "new": new_count, "proposed": 1 if proposed_id else 0}


def _esc(t: str) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--digest", action="store_true")
    args = ap.parse_args(argv)
    if args.digest:
        try:
            lines = []
            p = DATA / "email_triage.log.jsonl"
            if p.exists():
                for line in p.read_text().splitlines()[-8:]:
                    r = json.loads(line)
                    lines.append(f"{r.get('ts','')[:16]} new={r.get('new',0)} proposed={r.get('proposed',0)}")
            if lines:
                print("📬 Triage log:\n" + "\n".join(lines))
            else:
                print("📬 No triage activity yet.")
        except Exception as e:
            print(f"error: {e}")
    else:
        r = run()
        print(json.dumps(r, indent=2))
        return 0 if r.get("ok") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())