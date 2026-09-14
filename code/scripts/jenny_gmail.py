#!/usr/bin/env python3
"""jenny_gmail.py — Gmail perception for Jenny.

Reads unread inbox via the existing Google OAuth stack
(~/.hermes/gmail/{credentials,token}.json, gmail_reader.py service), then uses
the hop gateway to classify each message:
    actionable   -> needs Rohit or the team to DO something
    follow-up    -> an item Jenny should track / nudge later
    informational-> FYI only
    ignore       -> newsletters, alerts, junk

Actionable + follow-up messages become bus tasks in area=jenny owned=rohit
(status=ready), which wakes Jenny instantly via the SSE reactive daemon. Seen
message ids are remembered (state file) so we only surface each inbox once.

Pure stdlib + the google client libs already present in system python3.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.path.expanduser("~/.hermes"))
STATE_FILE = HERMES_HOME / "state" / "jenny_gmail_seen.json"
MAX_EMAILS = 8
MAX_BODY = 900


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"seen": {}, "last_scan": None}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _mark_seen(state: dict, msg_id: str, kind: str, snippet: str):
    seen = state.setdefault("seen", {})
    seen[msg_id] = {"kind": kind, "snippet": snippet[:200],
                    "ts": datetime.now(timezone.utc).isoformat()}
    # keep last 200 ids
    if len(seen) > 200:
        for k in list(seen)[:-200]:
            seen.pop(k, None)
    state["last_scan"] = datetime.now(timezone.utc).isoformat()


def _fetch() -> list[dict]:
    """Return recent unread messages [{id, from_, subject, snippet, body}]."""
    import base64
    from gmail_reader import _get_service
    try:
        svc = _get_service()
    except Exception as e:
        return [{"error": "gmail service unavailable: %s" % e}]
    try:
        resp = svc.users().messages().list(userId="me", q="in:inbox is:unread",
                                           maxResults=MAX_EMAILS).execute()
    except Exception as e:
        return [{"error": "gmail list failed: %s" % e}]
    out = []
    for m in resp.get("messages", []):
        try:
            meta = svc.users().messages().get(userId="me", id=m["id"],
                                              format="metadata",
                                              metadataHeaders=["From", "Subject"]).execute()
            headers = {h["name"].lower(): h["value"] for h in meta.get("payload", {}).get("headers", [])}
            body = ""
            try:
                full = svc.users().messages().get(userId="me", id=m["id"],
                                                  format="full").execute()
                payload = full.get("payload", {})
                if payload.get("parts"):
                    for part in payload["parts"]:
                        if part.get("mimeType", "").startswith("text/plain"):
                            body += base64.urlsafe_b64decode(part.get("body", {}).get("data", "")).decode(errors="ignore")
                else:
                    body = base64.urlsafe_b64decode(payload.get("body", {}).get("data", "")).decode(errors="ignore")
            except Exception:
                body = ""
            out.append({
                "id": m["id"],
                "from": headers.get("from", "?"),
                "subject": headers.get("subject", "(no subject)"),
                "snippet": meta.get("snippet", ""),
                "body": body[:MAX_BODY],
            })
        except Exception:
            continue
    return out


def _classify(msg: dict) -> dict:
    """LLM verdict: {kind, summary, action, agent}. Fallback = informational."""
    import jenny_llm
    prompt = """You are Jenny, Chief of Staff. Classify this inbox email for me.
From: %s
Subject: %s
Snippet: %s
Body: %s

Return STRICT JSON:
{"kind": "actionable"|"follow-up"|"informational"|"ignore",
 "summary": "15 words max",
 "action": "what should be done (or '')",
 "agent": "agent from roster to delegate to (or '')"}
Rules: invoices/bills->finlay, hardware/homelab->baseplate, appointments->calendula,
relationships/contacts->connector. If unsure, informational/action=''.
""" % (msg.get("from", "?")[:150], msg.get("subject", "")[:150],
       msg.get("snippet", "")[:300], msg.get("body", "")[:600])
    text = jenny_llm.hop_ask(prompt, max_tokens=180)
    parsed = jenny_llm._parse_json(text) if text else None
    if parsed and parsed.get("kind") in ("actionable", "follow-up", "informational", "ignore"):
        return parsed
    return {"kind": "informational", "summary": msg.get("subject", "")[:80],
            "action": "", "agent": ""}


def scan(max_unseen: int = 4) -> list[dict]:
    """Scan inbox, classify, create jenny bus tasks for actionable/follow-up.

    Returns list of created-item dicts (also includes seen ids, no duplicates).
    """
    state = _load_state()
    msgs = _fetch()
    if msgs and msgs[0].get("error"):
        return [{"error": msgs[0]["error"]}]
    created = []
    new_count = 0
    for msg in msgs:
        if msg["id"] in state.get("seen", {}):
            continue
        new_count += 1
        if len(created) >= max_unseen:
            break
        verdict = _classify(msg)
        kind = verdict.get("kind", "informational")
        summary = verdict.get("summary", msg.get("subject", ""))[:140]
        action = verdict.get("action", "")[:200]
        agent = verdict.get("agent", "")
        _mark_seen(state, msg["id"], kind, summary)

        if kind in ("actionable", "follow-up") and action:
            title = "📧 %s" % (action if len(action.split()) > 3 else summary)
            ok = _post_task(
                title,
                note="gmail:%s | from:%s | %s" % (msg["id"], msg.get("from", "?")[:60], summary),
                agent=agent,
            )
            created.append({"id": msg["id"], "kind": kind, "title": title,
                            "agent_hint": agent, "board_task": ok})
    _save_state(state)
    return {"scanned": new_count, "created": created, "state_file": str(STATE_FILE)}


def _post_task(title: str, note: str, agent: str = "") -> bool:
    import urllib.request
    area = agent if agent else "jenny"
    payload = json.dumps({"op": "add", "area": area, "title": title,
                          "owner": "rohit", "status": "ready", "priority": "normal",
                          "note": note[:200]}).encode()
    req = urllib.request.Request("http://127.0.0.1:9107/task", data=payload,
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5).read()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    print(json.dumps(scan(), indent=2, default=str))