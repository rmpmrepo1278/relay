#!/usr/bin/env python3
"""human_overrides.py — the sovereign governor.

Two responsibilities, both grafted onto the existing Agent Parliament:

A. JURISDICTION GATE (runs inside council tally)
   When a proposal is about to be approved, check whether the action touches
   *personal* data (is_personal_domain). If yes, it must NOT autopilot: we
   require a human 6th vote -> surface to Telegram with a reply ballot.
   If no (pure infra), the approved action gets a reversible [trial] suffix
   so commitment_executor runs it in a rollback-friendly way.

B. OVERRIDE SCAN (own scheduled job)
   Scans data/alerts_inbox.jsonl (the alert/approval inbox) for items marked
   requires_approval=True that are not yet delivered, and pages a compact
   human ballot summarizing what needs approval.

CLI:
  python3 human_overrides.py --gate <action_key> [--human-yes/--human-no]
      :: called by council; returns jurisdiction verdict + (optional) human vote
  python3 human_overrides.py --scan
      :: stand-alone scan of the approval inbox for undelivered human ballots
  python3 human_overrides.py --dry-run
      :: scan only, don't page / mark delivered
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from experience_builds import (
    DATA, STATE, page_telegram, is_personal_domain, trial_tag, TRIAL_MARK,
    within_window, mark_run, read_json, write_json, _now,
)

APPROVALS_FILE = DATA / "alerts_inbox.jsonl"
HUMAN_VOTES = STATE / "human_votes.json"
BALLOTS = STATE / "human_ballots.json"
SCAN_WINDOW = "override_scan_window"
SCAN_DEDUP_HOURS = float(os.environ.get("OVERRIDE_SCAN_HOURS", "2"))

# Ballot lifecycle: a personal action waits for your 6th vote, re-pages at most
# BALLOT_MAX_PAGES times across BALLOT_TTL_HOURS, then expires (declined).
BALLOT_TTL_HOURS = float(os.environ.get("HUMAN_BALLOT_TTL_HOURS", "72"))
BALLOT_MAX_PAGES = int(os.environ.get("HUMAN_BALLOT_MAX_PAGES", "3"))


def _alerts_file() -> Path:
    """The approval inbox (written by alerts_delivery.py / commitment_executor /
    email_intelligence) lives in the hermes data dir."""
    return APPROVALS_FILE


# ──────────────────────────────────────
# A. Jurisdiction gate
# ──────────────────────────────────────
def _load_human_votes() -> dict:
    return read_json(HUMAN_VOTES, {})


def _save_human_votes(v: dict) -> bool:
    return write_json(HUMAN_VOTES, v)


def ballot_token(action_key: str) -> str:
    """Deterministic, stable short token for a ballot (8 hex of sha1)."""
    return hashlib.sha1((action_key or "").encode("utf-8")).hexdigest()[:8]


def register_ballot(action_key: str) -> str:
    """Register an active ballot token -> action, so a Telegram reply can resolve.
    Each registration increments the page count (fresh = 1)."""
    token = ballot_token(action_key)
    ballots = read_json(BALLOTS, {})
    prev = ballots.get(token, {})
    pages = int(prev.get("pages", 0) or 0) + 1
    ballots[token] = {"action_key": action_key, "paged_at": _now(), "pages": pages}
    write_json(BALLOTS, ballots)
    return token


def ballot_lifecycle(action_key: str) -> dict:
    """Where a ballot stands: pending (fresh), needs re-page, or expired.

    - not registered yet          -> should_page=True (fresh)
    - registered, age < TTL       -> hold silently (no 5-min flooding)
    - registered, age > TTL       -> re-page (pages+1) unless pages exhausted
    - pages >= MAX and stale      -> expired: the action dies quietly
    """
    token = ballot_token(action_key)
    b = read_json(BALLOTS, {}).get(token)
    paged_at = b.get("paged_at") if b else None
    pages = int(b.get("pages", 0) if b else 0)
    age_h = None
    if paged_at:
        try:
            age_h = (datetime.now(timezone.utc) -
                     datetime.fromisoformat(paged_at)).total_seconds() / 3600
        except Exception:
            age_h = None
    paged = bool(paged_at)
    stale = age_h is not None and age_h > BALLOT_TTL_HOURS
    expired = paged and stale and pages >= BALLOT_MAX_PAGES
    should_page = (not paged) or (stale and not expired)
    return {"paged": paged, "paged_at": paged_at, "pages": pages,
            "age_hours": age_h, "stale": stale, "expired": expired,
            "should_page": should_page, "ttl_hours": BALLOT_TTL_HOURS,
            "max_pages": BALLOT_MAX_PAGES}


def repage_ballot(action_key: str) -> str:
    """Push the ballot again (counts as a fresher page) and re-page."""
    token = register_ballot(action_key)
    ballot = read_json(BALLOTS, {}).get(token, {})
    page_telegram(
        f"🗳️ **Still awaiting your 6th vote** (page {ballot.get('pages')}):\n"
        f"`{action_key}`\n"
        f"Ballot #{token}\n\n"
        f"Reply `yes` to allow it or `no` to decline — this expires after "
        f"{BALLOT_MAX_PAGES} pages."
    )
    return token


def expire_ballot(action_key: str) -> bool:
    """Ballot ran out of pages -> remove it and page the decline note."""
    token = ballot_token(action_key)
    ballots = read_json(BALLOTS, {})
    if token in ballots:
        ballots.pop(token, None)
        write_json(BALLOTS, ballots)
    page_telegram(
        f"⏰ Ballot for `{action_key}` expired after {BALLOT_MAX_PAGES} pages "
        f"with no reply — action NOT run. You can always ask for it again."
    )
    return True


def cleanup_ballots() -> dict:
    """Drop ballot entries whose action no longer has an open pending proposal
    (finalized / rejected / never proposed). Keeps the ledger tight."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from decision_council import VOTES_FILE
        votes = read_json(VOTES_FILE, {})
        open_actions = {v.get("action_key") for v in votes.values() if isinstance(v, dict)}
        ballots = read_json(BALLOTS, {})
        removed = [tok for tok, b in ballots.items()
                   if b.get("action_key") not in open_actions]
        for tok in removed:
            ballots.pop(tok, None)
        if removed:
            write_json(BALLOTS, ballots)
        return {"removed": removed}
    except Exception:
        return {"removed": []}


def human_vote_record(action_key: str, should_prompt: bool = True) -> dict:
    """Return whether this action needs a human 6th vote, and (if present) the
    recorded human decision from the votes file."""
    votes = _load_human_votes()
    rec = votes.get(action_key)
    personal = is_personal_domain(action_key)
    return {
        "action_key": action_key,
        "is_personal": personal,
        "requires_human": personal and should_prompt,
        "human_vote": rec.get("vote") if rec else None,
        "human_voted_at": rec.get("when") if rec else None,
        "suffix": TRIAL_MARK if not personal else None,
    }


def __gate_cli(argv) -> int:
    # gate mode: parse --gate <action>, optional --human-yes / --human-no
    arg = [a for a in argv if a.startswith("--")]
    action = None
    for i, a in enumerate(argv):
        if a == "--gate" and i + 1 < len(argv):
            action = argv[i + 1]
    if not action:
        print(json.dumps({"error": "usage: --gate <action_key>"}, indent=2))
        return 2

    human_yes = "--human-yes" in argv
    human_no = "--human-no" in argv
    if human_yes or human_no:
        votes = _load_human_votes()
        votes[action] = {"vote": "yes" if human_yes else "no",
                         "when": _now()}
        _save_human_votes(votes)

    gate = human_vote_record(action, should_prompt=not human_yes and not human_no)
    # If personal + no explicit human signal yet -> surface ballot and mark pending
    if gate["requires_human"] and not gate["human_vote"]:
        _page_approval_ballot(action, gate)
    print(json.dumps(gate, indent=2))
    return 0


def _page_telegram_ballot(action_key: str, token: str) -> None:
    page_telegram(
        f"🗳️ **Human override required** — this action touches *your* data:\n"
        f"`{action_key}`\n"
        f"Ballot #{token}\n\n"
        f"The council wants to act, but that's your jurisdiction.\n"
        f"Reply to this message with `yes` or `no` (or send `yes {token}`) "
        f"and I'll record the 6th vote."
    )


def _page_approval_ballot(action_key: str, gate: dict) -> None:
    token = register_ballot(action_key)
    _page_telegram_ballot(action_key, token)


def route_correction(action_key: str, source: str = "experience") -> dict:
    """Join the approval pipeline with a correction proposed by an experience
    module (monthly verdict, radiator, avatar). Personal-domain corrections are
    held for the human 6th vote; infra corrections go out with a [trial] tag."""
    gate = human_vote_record(action_key)
    res = {"action": action_key, "source": source}
    if gate["requires_human"] and not gate["human_vote"]:
        _page_approval_ballot(action_key, gate)
        res["gate"] = "pending-human"
        return res
    if gate["human_vote"] == "no":
        res["gate"] = "rejected-human"
        return res
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import decision_council as dc
    if gate["is_personal"]:
        dc._enqueue(action_key)
        res["gate"] = "enqueued-human-approved"
    else:
        dc._enqueue(f"{action_key} {TRIAL_MARK}".strip())
        res["gate"] = "enqueued-trial"
    return res


# ──────────────────────────────────────
# B. Approval-inbox scan
# ──────────────────────────────────────
def scan_approvals(dry: bool = False) -> list[dict]:
    undelivered = []
    try:
        inbox = _alerts_file()
        if inbox.exists():
            raw = inbox.read_text(errors="ignore").strip()
            if raw:
                data = json.loads(raw)
                if isinstance(data, list):
                    for entry in data:
                        if entry.get("requires_approval") and not entry.get("delivered"):
                            undelivered.append({
                                "message": entry.get("message", ""),
                                "severity": entry.get("severity", "info"),
                                "source": entry.get("source", "alerts_inbox"),
                                "timestamp": entry.get("timestamp", ""),
                            })
    except Exception:
        return []

    if undelivered and not dry:
        lines = ["🗳️ **Approval inbox**"]
        for u in undelivered[:5]:
            lines.append(f"- [{u['severity']}] {u['message'][:140]}")
        page_telegram("\n".join(lines))
        mark_run(SCAN_WINDOW, scanned=len(undelivered))
        # mark delivered so we don't re-page every scan
        _mark_delivered(list(undelivered))
    return undelivered


def _mark_delivered(entries: list[dict]) -> None:
    try:
        inbox = _alerts_file()
        if inbox.exists():
            raw = inbox.read_text(errors="ignore").strip()
            if raw:
                data = json.loads(raw)
                if isinstance(data, list):
                    for e in data:
                        for u in entries:
                            if e.get("message") == u.get("message") and e.get("timestamp") == u.get("timestamp"):
                                e["delivered"] = True
                    inbox.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def main(argv):
    dry = "--dry-run" in argv
    if "--gate" in argv:
        return __gate_cli(argv)
    if "--scan" in argv or dry:
        result = scan_approvals(dry=dry)
        print(json.dumps(result, indent=2, default=str))
        return 0
    # default: scan
    result = scan_approvals(dry=dry)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))