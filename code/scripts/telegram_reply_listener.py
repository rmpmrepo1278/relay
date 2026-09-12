#!/usr/bin/env python3
"""telegram_reply_listener.py — turns your Telegram reply into the human 6th vote.

Run by the scheduler every minute. Long-polls the bot's getUpdates, and for each
incoming message that is:
  * a reply to a council ballot (matched by our machine-readable `Ballot #<hex>`),
  * OR an explicit "yes/no <ballot-token>" message,
  * OR an unambiguous yes/no (exactly one human action awaiting your verdict),
and comes from your home channel, it records the vote in human_votes.json so the
council's next tally releases (or suppresses) the action.

Also pages a confirmation so you know it landed.

CLI:
  python3 telegram_reply_listener.py          # run one poll cycle, then exit
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from experience_builds import STATE, write_json, read_json, _now
from human_overrides import _load_human_votes, _save_human_votes, ballot_token, HUMAN_VOTES

# ─── Agent-kit command + voice handling (added by Relay 2026-09-12) ───
try:
    import commands as agent_commands
    import voice_ingest
    from agent_kits import DATA as AGENT_DATA
    from agent_kits import append_jsonl as _append_jsonl
except Exception:
    agent_commands = None
    voice_ingest = None
    AGENT_DATA = None
    _append_jsonl = None

TG_INBOX = (AGENT_DATA / "tg_inbox.jsonl") if AGENT_DATA else None

OFFSET_FILE = STATE / "tg_listener_offset.json"
BALLOTS_FILE = STATE / "human_ballots.json"
API = "https://api.telegram.org/bot{}/getUpdates"


# ──────────────────────────────────────
# Pure decision logic (unit-testable)
# ──────────────────────────────────────
def parse_vote(text: str) -> str | None:
    """Map a human message to 'yes' / 'no' / None."""
    t = (text or "").strip().lower()
    if t.startswith(("yes", "yep", "approve", "confirm", "ok", "\U0001f44d", "go")):
        return "yes"
    if t.startswith(("no", "nope", "decline", "deny", "reject", "\U0001f44e", "stop")):
        return "no"
    return None


def extract_ballot_token(text: str) -> str | None:
    """Pull the ballot token out of text: either `Ballot #<hex>` or a bare
    standalone 8-hex token (e.g. a direct message like 'no 3f7a2c9e')."""
    import re
    m = re.search(r"Ballot #([0-9a-fA-F]{8})|\b([0-9a-fA-F]{8})\b", text or "")
    if not m:
        return None
    return (m.group(1) or m.group(2)).lower()


def load_ballots() -> dict:
    return read_json(BALLOTS_FILE, {})


def save_ballots(b: dict) -> bool:
    return write_json(BALLOTS_FILE, b)


def _home_chat_id() -> str:
    return os.environ.get("TELEGRAM_HOME_CHANNEL", os.environ.get("TELEGRAM_CHAT_ID", ""))


def _allowed_user() -> str:
    """Comma-separated allowed user ids (`TELEGRAM_ALLOWED_USERS`) or single."""
    v = os.environ.get("TELEGRAM_ALLOWED_USERS", os.environ.get("TELEGRAM_ALLOWED_USER", ""))
    return str(v or "")


def resolve_action(text: str, quoted: str, ballots: dict, pending_keys: list[str]) -> str | None:
    """Determine which pending action this reply refers to."""
    # 1) reply-to ballot token (or token embedded in either text)
    for src in (quoted, text):
        tok = extract_ballot_token(src or "")
        if tok and tok in ballots:
            return ballots[tok].get("action_key")
    # 2) unambiguous single pending human action
    if pending_keys and len(pending_keys) == 1:
        return pending_keys[0]
    return None


def record_human_vote(action_key: str, vote: str, ballot: str | None = None) -> bool:
    votes = _load_human_votes()
    votes[action_key] = {"vote": vote, "when": _now()}
    if ballot:
        votes[action_key]["ballot"] = ballot
    if not _save_human_votes(votes):
        return False
    if ballot:
        b = load_ballots()
        if ballot in b:
            b.pop(ballot)
            save_ballots(b)
    return True


def pending_human_keys() -> list[str]:
    """Actions currently awaiting the human 6th vote (from decision_votes slate)."""
    try:
        votes = read_json(STATE / "decision_votes.json", {})
        out = []
        for pid, prop in votes.items():
            if not isinstance(prop, dict):
                continue
            ek = prop.get("action_key", "")
            votes_dict = prop.get("votes", {})
            voted = sum(1 for x in votes_dict.values()
                        if x in ("yes", "no", "abstain-yes", "abstain-no"))
            yes = sum(1 for x in votes_dict.values() if x in ("yes", "abstain-yes"))
            if voted >= 3 and yes >= 2:  # quorum+approved but not yet finalized
                out.append(ek)
        return out
    except Exception:
        return []


# ──────────────────────────────────────
# Network layer (guarded; never crashes the scheduler)
# ──────────────────────────────────────
def fetch_updates(offset: int | None = None) -> list[dict]:
    bot = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = _home_chat_id()
    if not bot or not chat:
        print("Telegram credentials not set, skipping", file=sys.stderr)
        return []
    params = {"timeout": 25, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(API.format(bot), params=params, timeout=30)
        if r.status_code != 200:
            print(f"Telegram getUpdates {r.status_code}: {r.text[:160]}", file=sys.stderr)
            return []
        data = r.json()
        if not data.get("ok"):
            print(f"Telegram API error: {data}", file=sys.stderr)
            return []
        return data.get("result", [])
    except Exception as e:
        print(f"Telegram getUpdates error: {e}", file=sys.stderr)
        return []


def _from_allowed_chat(update: dict) -> bool:
    """Fail-closed: without a configured home chat, no vote is accepted."""
    allowed = _home_chat_id()
    if not allowed:
        return False
    msg = update.get("message", {})
    chat_id = str(msg.get("chat", {}).get("id", ""))
    # env may be "chatid" or "chatid:threadid" (topic/thread mode)
    parts = str(allowed).split(":")
    allowed_chat = parts[0]
    allowed_thread = parts[1] if len(parts) > 1 else ""
    if chat_id != allowed_chat:
        return False
    if allowed_thread:
        thread = msg.get("message_thread_id", "")
        if str(thread) != str(allowed_thread):
            return False
    uid = str(msg.get("from", {}).get("id", ""))
    au = _allowed_user()
    if au:
        allowed_ids = [x.strip() for x in au.split(",") if x.strip()]
        if allowed_ids and uid not in allowed_ids:
            return False
    return True


def process_update(update: dict) -> dict:
    """Handle one update. Returns {status, ...}. Files are the ledger."""
    msg = update.get("message", {})
    if not msg:
        return {"status": "skip-not-message"}
    text = msg.get("text", "")
    _log_inbound(update, text)

    voice = msg.get("voice") or msg.get("audio")
    if not text and voice and voice_ingest is not None:
        try:
            if not _from_allowed_chat(update):
                return {"status": "skip-not-allowed-chat"}
            chat_id = int(msg["chat"]["id"])
            fid = voice.get("file_id", "")
            out = voice_ingest.handle_voice(fid, chat_id=chat_id)
            return {"status": "voice", "detail": out.get("ok") and "transcribed" or "error"}
        except Exception as e:
            return {"status": "voice-error", "error": str(e)[:80]}

    if not text:
        return {"status": "skip-no-text"}

    if text.startswith("/") and agent_commands is not None:
        try:
            if not _from_allowed_chat(update):
                return {"status": "skip-not-allowed-chat"}
            chat_id = int(msg["chat"]["id"])
            reply = agent_commands.handle(text, update=update)
            if reply:
                from telegram_bridge import send_telegram
                send_telegram(reply, chat_id=chat_id)
            return {"status": "command", "cmd": text.split()[0]}
        except Exception as e:
            return {"status": "command-error", "error": str(e)[:80]}

    vote = parse_vote(text)
    if not vote:
        return {"status": "skip-unrecognized", "text": text[:40]}
    if not _from_allowed_chat(update):
        return {"status": "skip-not-allowed-chat"}
    quoted = msg.get("reply_to_message", {}).get("text", "")
    ballots = load_ballots()
    action = resolve_action(text, quoted, ballots, pending_human_keys() or [])
    if not action:
        return {"status": "no-action-resolved", "text": text[:40]}
    ballot_tok = extract_ballot_token(quoted or "") or extract_ballot_token(text or "")
    ok = record_human_vote(action, vote, ballot=ballot_tok)
    if not ok:
        return {"status": "record-failed", "action": action}
    return {"status": "recorded", "action": action, "vote": vote}


def _log_inbound(update: dict, text: str) -> None:
    """Persist every allowed inbound to data/tg_inbox.jsonl for the whole stack."""
    try:
        if not _from_allowed_chat(update):
            return
        if _append_jsonl is None or TG_INBOX is None:
            return
        msg = update.get("message", {})
        _append_jsonl(TG_INBOX, {
            "ts": _now(),
            "chat_id": str(msg.get("chat", {}).get("id", "")),
            "from": str(msg.get("from", {}).get("id", "")),
            "type": msg.get("voice") or msg.get("audio") or "text",
            "text": (text or "")[:500],
        })
    except Exception:
        pass

    # cheap rotation: cap tg_inbox so it never grows unbounded
    try:
        if TG_INBOX is not None and TG_INBOX.exists() and _append_jsonl is not None:
            from agent_kits import trim_jsonl as _trim
            _trim(TG_INBOX, 1000)
    except Exception:
        pass


# ──────────────────────────────────────
# Confirmation circuit breaker (never flood Telegram)
# ──────────────────────────────────────
CONFIRM_FILE = STATE / "tg_confirmations.json"
CONFIRM_BURST_MAX = 3
CONFIRM_BURST_WINDOW = 600  # seconds


def _confirm_state() -> dict:
    st = read_json(CONFIRM_FILE, {})
    for k in ("actions", "burst"):
        st.setdefault(k, {})
    return st


def _should_confirm(action: str, vote_when: str) -> bool:
    """True if we should page a confirmation: never twice for the same vote,
    and at most CONFIRM_BURST_MAX confirmations per 10 minutes."""
    st = _confirm_state()
    prev = st["actions"].get(action, {})
    if prev.get("vote_when") == vote_when and prev.get("confirmed_at"):
        return False
    now = datetime.now(timezone.utc)
    burst = [t for t in st["burst"]
             if (now - datetime.fromisoformat(t)).total_seconds() <= CONFIRM_BURST_WINDOW] \
        if isinstance(st.get("burst"), list) else []
    return len(burst) < CONFIRM_BURST_MAX


def _mark_confirm(action: str, vote_when: str) -> None:
    from datetime import timedelta
    now = _now()
    st = _confirm_state()
    st["actions"][action] = {"confirmed_at": now, "vote_when": vote_when}
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=CONFIRM_BURST_WINDOW)).isoformat()
    burst = [t for t in st.get("burst", [])
             if isinstance(t, str) and t >= cutoff]
    burst.append(now)
    st["burst"] = burst[-CONFIRM_BURST_MAX * 2:]
    write_json(CONFIRM_FILE, st)


# ──────────────────────────────────────
# Poll once (scheduler cadence)
# ──────────────────────────────────────
def poll_once() -> dict:
    offset = int(read_json(OFFSET_FILE, {}).get("offset", 0) or 0)
    updates = fetch_updates(offset + 1 if offset else None)
    results = []
    if updates:
        for u in updates:
            res = process_update(u)
            results.append(res)
            if res["status"] == "recorded":
                votes = read_json(HUMAN_VOTES, {})
                when = str((votes.get(res["action"]) or {}).get("when", "")) if votes else ""
                if _should_confirm(res["action"], when):
                    from experience_builds import page_telegram
                    page_telegram(
                        f"🗳️ Vote recorded: **{res['vote'].upper()}** on `{res['action']}`.\n"
                        f"The council finalizes on its next tally cycle."
                    )
                    _mark_confirm(res["action"], when)
        max_id = max(u.get("update_id", 0) for u in updates)
        if max_id:
            write_json(OFFSET_FILE, {"offset": max_id, "last": _now()})
    return {"polled": len(updates), "results": results}


def main(argv):
    res = poll_once()
    print(json.dumps(res, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))