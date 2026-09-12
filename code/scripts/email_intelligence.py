#!/usr/bin/env python3
"""email_intelligence.py — Fetch, categorize, and surface actionable emails.

Reads Gmail via API, categorizes messages, pushes summaries and action items
to alerts_inbox for Telegram delivery. Runs daily via scheduler.
"""
import json
import os
import pickle
import base64
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

HOME = Path.home()
HERMES_HOME = HOME / ".hermes"
GMAIL_DIR = HERMES_HOME / "gmail"
ALERTS_INBOX = HOME / ".hermes" / "data" / "alerts_inbox.jsonl"
EMAIL_SEEN_CACHE = HERMES_HOME / "data" / "email_ids_seen.json"
TOKEN_FILE = GMAIL_DIR / "token.json"
CREDS_FILE = GMAIL_DIR / "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]
CATEGORIES = {
    "actionable": ["invoice", "bill", "payment due", "action required", "please review",
                   "approval needed", "sign", "deadline", "rsvp", "confirm"],
    "career": ["job offer", "interview", "recruiter", "application", "hiring",
               "opportunity", "position", "salary", "resume", "cv"],
    "financial": ["statement", "receipt", "subscription", "renewal", "charged",
                  "payment received", "refund", "transaction"],
    "security": ["password reset", "login", "suspicious", "security alert",
                 "2fa", "authenticator", "device added", "new sign-in"],
    "meeting": ["meeting", "calendar", "invite", "confirmed", "rescheduled",
                "canceled", "zoom", "google meet", "teams"],
}

MAX_EMAILS = 20
LOOKBACK_HOURS = 24


def get_gmail_service():
    """Build and return a Gmail API service with valid credentials.

    Retries transient auth/network failures (e.g. oauth2.googleapis.com
    unreachable) with exponential backoff before giving up.
    """
    import time
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    last_err = None
    for attempt in range(3):
        try:
            creds = None
            if TOKEN_FILE.exists():
                creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
                    try:
                        creds = flow.run_local_server(port=0)
                    except Exception:
                        # Headless fallback: print URL, prompt for code
                        auth_url, _ = flow.authorization_url(
                            access_type="offline",
                            prompt="consent",
                        )
                        print("Gmail auth needed. Visit:\n", auth_url)
                        try:
                            code = input("Paste authorization code: ").strip()
                        except EOFError:
                            print("\nNo input received. Auth incomplete — token not saved.")
                            raise  # Let retry handle or exit
                        if code:
                            flow.fetch_token(code=code)
                            creds = flow.credentials
                        else:
                            raise RuntimeError("No authorization code provided")
                if creds:
                    TOKEN_FILE.write_text(creds.to_json())

            return build("gmail", "v1", credentials=creds)
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(2 ** attempt * 5)
    raise last_err


def categorize_email(subject: str, snippet: str) -> list:
    """Categorize an email based on subject and snippet content."""
    text = f"{subject} {snippet}".lower()
    matched = []
    for cat, keywords in CATEGORIES.items():
        if any(kw in text for kw in keywords):
            matched.append(cat)
    return matched or ["informational"]


def fetch_recent_emails(service):
    """Fetch recent emails from inbox."""
    after = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).strftime("%Y/%m/%d")
    query = f"in:inbox after:{after}"

    results = service.users().messages().list(userId="me", q=query, maxResults=MAX_EMAILS).execute()
    messages = results.get("messages", [])

    emails = []
    seen = set()
    try:
        seen = set(json.loads(EMAIL_SEEN_CACHE.read_text())) if EMAIL_SEEN_CACHE.exists() else set()
    except: pass
    for msg in messages:
        data = service.users().messages().get(userId="me", id=msg["id"], format="metadata",
                                              metadataHeaders=["From", "Subject", "Date"]).execute()
        headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
        subject = headers.get("Subject", "(no subject)")
        sender = headers.get("From", "(unknown)")
        snippet = data.get("snippet", "")
        categories = categorize_email(subject, snippet)

        emails.append({
            "id": msg["id"],
            "subject": subject,
            "from": sender,
            "snippet": snippet[:200],
            "categories": categories,
            "date": headers.get("Date", ""),
        })

    # Save seen cache
    try:
        EMAIL_SEEN_CACHE.write_text(json.dumps(list(seen)))
    except: pass
    return emails


def format_digest(emails: list) -> str:
    """Compose a categorized email digest."""
    if not emails:
        return "📬 No new emails in the last 24 hours."

    by_category = {}
    for e in emails:
        for cat in e["categories"]:
            by_category.setdefault(cat, []).append(e)

    priority_order = ["actionable", "career", "financial", "security", "meeting", "informational"]
    lines = [f"📬 Email Digest — {len(emails)} new in {LOOKBACK_HOURS}h", ""]

    for cat in priority_order:
        items = by_category.pop(cat, [])
        if not items:
            continue
        icon = {"actionable": "⚡", "career": "💼", "financial": "💰", "security": "🔒",
                "meeting": "📅", "informational": "📄"}.get(cat, "📄")
        lines.append(f"{icon} *{cat.title()}* ({len(items)})")
        for e in items[:3]:
            sender_short = e["from"].split("<")[0].strip()[:25]
            lines.append(f"  • {e['subject'][:60]}")
            lines.append(f"    {sender_short}")
        if len(items) > 3:
            lines.append(f"  ... and {len(items)-3} more")
        lines.append("")

    # Remaining unlisted categories
    for cat, items in by_category.items():
        if items:
            lines.append(f"📎 {cat.title()}: {len(items)}")
            lines.append("")

    return "\n".join(lines)


def push_to_inbox(message: str, severity: str = "info"):
    """Push digest to alerts_inbox for Telegram delivery."""
    entry = {
        "severity": severity,
        "message": message,
        "source": "email_intelligence",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "delivered": False,
        "requires_approval": False,
        "actions": [],
    }
    try:
        ALERTS_INBOX.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if ALERTS_INBOX.exists():
            try:
                content = ALERTS_INBOX.read_text().strip()
                if content and content.startswith("["):
                    existing = json.loads(content)
            except (json.JSONDecodeError, OSError):
                existing = []
        existing.append(entry)
        ALERTS_INBOX.write_text(json.dumps(existing, indent=2))
        return True
    except OSError:
        return False


def _log_only(msg: str) -> None:
    try:
        (HERMES_HOME / "logs" / "email_intelligence.log").parent.mkdir(parents=True, exist_ok=True)
        with (HERMES_HOME / "logs" / "email_intelligence.log").open("a") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n")
    except OSError:
        pass


def run():
    if not TOKEN_FILE.exists():
        print("Gmail OAuth not configured yet (no token.json) — skipping quietly")
        _log_only("Email intelligence: skipped — Gmail OAuth not configured (no token.json)")
        return
    try:
        service = get_gmail_service()
    except Exception as e:
        print(f"Gmail auth failed: {e}")
        _log_only(f"Email intelligence: auth failed — {e}")
        push_to_inbox(f"⚠️ Email intelligence: auth failed — {e}", "warning")
        return

    emails = fetch_recent_emails(service)
    digest = format_digest(emails)

    # Skip empty digests (no "No new emails" noise)
    if emails:
        push_to_inbox(digest)

    # Also push separate alerts for high-priority items
    for e in emails:
        if "actionable" in e["categories"] or "career" in e["categories"]:
            alert = f"⚡ *{e['subject'][:80]}*\n{e['from'][:60]}\n{e['snippet'][:200]}"
            push_to_inbox(alert, "warning" if "actionable" in e["categories"] else "info")

    print(f"Email digest: {len(emails)} emails, {sum(1 for e in emails if 'actionable' in e['categories'])} actionable")


# ─── Write-capable authoring (OAuth: gmail.send + gmail.compose) ──────────

def send_email(to: str, subject: str, body: str,
                reply_to_id: str | None = None) -> dict:
    """Send an email via Gmail API. Returns the API result."""
    service = get_gmail_service()
    import base64
    from email.mime.text import MIMEText

    if reply_to_id:
        message = MIMEText(body, "plain")
        message["In-Reply-To"] = reply_to_id
        message["References"] = reply_to_id
    else:
        message = MIMEText(body, "plain")
    message["To"] = to
    message["Subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    return {"success": True, "id": result.get("id"), "threadId": result.get("threadId")}


def draft_email(to: str, subject: str, body: str,
                 reply_to_id: str | None = None) -> dict:
    """Create a draft email without sending. Returns draft metadata."""
    service = get_gmail_service()
    import base64
    from email.mime.text import MIMEText

    message = MIMEText(body, "plain")
    message["To"] = to
    message["Subject"] = subject
    if reply_to_id:
        message["In-Reply-To"] = reply_to_id
        message["References"] = reply_to_id

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()


def propose_email_reply(sender: str, subject: str, snippet: str) -> dict:
    """Given an actionable email, propose a reply template for Telegram confirm-send."""
    # Heuristic reply: acknowledge + ask for timeline / action owner
    body = (
        f"Hi {sender.split('<')[0].strip()},\n\n"
        f"Thanks for the email about '{subject[:60]}'.\n\n"
        f"I've noted this and will follow up by EOD.\n\n"
        f"— Hermes (on your behalf; reply /send  or /skip)"
    )
    return {
        "proposed": True,
        "to": sender,
        "subject": f"Re: {subject[:80]}",
        "body": body,
        "original_snippet": snippet[:200],
        "confirm_cmd": f"/email-send \"{body[:80]}...\"",
    }


if __name__ == "__main__":
    import argparse as _ap
    _p = _ap.ArgumentParser()
    _p.add_argument("--auth", action="store_true", help="Force OAuth re-auth flow")
    _args = _p.parse_args()
    if _args.auth:
        # Remove token to force fresh auth
        TOKEN_FILE.unlink(missing_ok=True)
        # Use get_gmail_service's built-in retry loop, but break on stdin EOF
        try:
            svc = get_gmail_service()
            if svc:
                print("Gmail auth successful! Token saved.")
        except Exception as e:
            print(f"Gmail auth incomplete: {e}")
            print("To complete authentication, open the printed URL in a browser,")
            print("grant consent, and re-run this command pasting the code.")
    else:
        run()
