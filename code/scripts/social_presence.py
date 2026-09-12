#!/usr/bin/env python3
"""social_presence.py — Social Presence Intelligence (GitHub + LinkedIn signals).

Uses the unauthenticated GitHub public API (rate limit ~60/hr, fine for one
daily digest) and existing websearch via the orchestrator for LinkedIn signals.
Does NOT require gh CLI auth or API keys — public profile data only.

CLI:
  python3 social_presence.py digest   # compose and send a daily social presence digest
  python3 social_presence.py github   # GitHub-only activity summary
  python3 social_presence.py linkedin # LinkedIn public signal summary
  python3 social_presence.py --check  # dry-run, print without sending
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import request as _req

from agent_kits import HERMES_HOME, DATA, send, read_json, append_jsonl, now_iso

_GITHUB_USER = "rmpmrepo1278"
_STATE = HERMES_HOME / "data" / "social_presence_state.json"
_LINKEDIN_NAME = "Rohit Mishra"


def _get(url: str, accept: str = "application/vnd.github+json") -> dict | None:
    try:
        req = _req.Request(url, headers={
            "Accept": accept,
            "User-Agent": "hermes-social-presence/1.0",
        })
        with _req.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _esc(t: str) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def github_digest() -> dict:
    """Public GitHub activity for the last 7 days."""
    out = {"user": _GITHUB_USER, "repos": [], "events": 0, "followers": 0, "error": None}
    profile = _get(f"https://api.github.com/users/{_GITHUB_USER}")
    if not profile:
        out["error"] = "github rate-limited or unreachable"
        return out
    out["followers"] = profile.get("followers", 0)
    out["public_repos"] = profile.get("public_repos", 0)

    # recent public events (last 7 days)
    events = _get(f"https://api.github.com/users/{_GITHUB_USER}/events/public?per_page=30")
    if not events:
        return out
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent = []
    for ev in events:
        try:
            dt = datetime.fromisoformat(str(ev.get("created_at", "")).replace("Z", "+00:00"))
            if dt < cutoff:
                continue
        except Exception:
            continue
        recent.append(ev)
    out["events"] = len(recent)

    # count by type
    by_type = {}
    for ev in recent:
        t = ev.get("type", "")
        by_type[t] = by_type.get(t, 0) + 1
    out["event_breakdown"] = by_type

    # recent repos touched
    repo_names = {ev.get("repo", {}).get("name", "") for ev in recent if ev.get("repo", {}).get("name")}
    out["repos_touched"] = list(repo_names)[:8]
    return out


def linkedin_digest() -> dict:
    """LinkedIn public signals via existing search infrastructure.
    Returns minimal data — LinkedIn has no unauthenticated API; this relies
    on the career engine's search + future manual token provisioning."""
    return {"name": _LINKEDIN_NAME, "note": "LinkedIn API requires OAuth (no token provisioned yet). "
            "Career engine search covers LinkedIn job posts."}


def render(gh: dict, li: dict) -> str:
    lines = ["🌐 <b>Social Presence Digest</b>", ""]

    # GitHub
    if gh.get("error"):
        lines.append(f"GitHub: {_esc(gh['error'])}")
    else:
        lines.append(f"GitHub @{_esc(gh['user'])}:")
        lines.append(f"   {gh.get('public_repos',0)} public repos · {gh.get('followers',0)} followers")
        lines.append(f"   {gh['events']} events in the last 7d")
        if gh.get("repos_touched"):
            lines.append(f"   Active repos: {', '.join(gh['repos_touched'][:5])}")
        if gh.get("event_breakdown"):
            lines.append(f"   Types: {', '.join(f'{k}:{v}' for k,v in gh['event_breakdown'].items() if v)}")

    lines.append("")

    # LinkedIn
    lines.append(f"LinkedIn: {_esc(li.get('note', 'no token provisioned'))}")

    lines.append("")
    lines.append("💡 <i>Add a GITHUB_TOKEN to ~/.hermes/.env for richer data; "
                 "add a LinkedIn OAuth token for automated post tracking.</i>")
    return "\n".join(lines)


def digest(send_now: bool = True, dry_run: bool = False) -> str:
    gh = github_digest()
    li = linkedin_digest()
    text = render(gh, li)
    if not dry_run:
        send(text)
    append_jsonl(DATA / "social_presence_log.jsonl", {
        "ts": now_iso(), "github_events": gh.get("events", 0),
        "followers": gh.get("followers", 0), "dry_run": dry_run,
    })
    return text


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("digest")
    sub.add_parser("github")
    sub.add_parser("linkedin")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    if getattr(args, "check", False):
        gh = github_digest()
        li = linkedin_digest()
        print(render(gh, li))
        return 0
    if args.cmd == "github":
        print(json.dumps(github_digest(), indent=2))
    elif args.cmd == "linkedin":
        print(json.dumps(linkedin_digest(), indent=2))
    else:
        print(digest(send_now=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())