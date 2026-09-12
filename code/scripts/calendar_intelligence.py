#!/usr/bin/env python3
"""calendar_intelligence.py — Google Calendar integration for Hermes.

Fetches today's and upcoming events, provides meeting-aware briefings,
and sends reminders before events.

First run: performs OAuth (prints URL, paste back code).
Subsequent runs: auto-refreshes token silently.
"""

import json
import os
import subprocess
import pickle
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path.home() / ".hermes"
CALENDAR_DIR = HERMES / "calendar"
CREDS_FILE = HERMES / "google_client_secret.json"
TOKEN_FILE = CALENDAR_DIR / "token.json"
CACHE_FILE = HERMES / "state" / "calendar_events.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def send(text: str):
    try:
        from telegram_bridge import send_telegram
        send_telegram(text[:4096])
    except Exception:
        pass


def get_calendar_service():
    """Build and return a Calendar API service with valid credentials."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    CALENDAR_DIR.mkdir(parents=True, exist_ok=True)
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_FILE.exists():
                raise RuntimeError(
                    f"No credentials file at {CREDS_FILE}. "
                    "Copy your Google API client_secret.json there first."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDS_FILE), SCOPES,
                redirect_uri="http://localhost")
            auth_url, _ = flow.authorization_url(prompt="consent")
            # Save PKCE verifier so we can use the code later
            try:
                (HERMES / "calendar").mkdir(parents=True, exist_ok=True)
                with open(HERMES / "calendar" / "flow_verifier.pkl", "wb") as f:
                    pickle.dump(flow.code_verifier, f)
            except Exception as e:
                print(f"Warning: could not save verifier: {e}")
            msg = (
                "Calendar auth needed. Visit:\n"
                f"{auth_url}\n"
                "Then paste the authorization code back."
            )
            print(msg)
            send(msg)
            # Read code from stdin or from a temp file
            import sys as _sys
            code_or_url = _sys.stdin.readline().strip()
            import urllib.parse
            parsed = urllib.parse.urlparse(code_or_url)
            if parsed.query:
                qs = urllib.parse.parse_qs(parsed.query)
                code = qs.get("code", [""])[0]
            else:
                code = code_or_url
            if not code:
                # Try reading from a prompt file
                prompt_file = HERMES / "calendar" / "auth_code.txt"
                if prompt_file.exists():
                    code = prompt_file.read_text().strip()
            if code:
                verifier_file = HERMES / "calendar" / "flow_verifier.pkl"
                if verifier_file.exists():
                    try:
                        flow.code_verifier = pickle.loads(verifier_file.read_bytes())
                    except Exception as e:
                        print(f"Warning: could not restore verifier: {e}")
                flow.fetch_token(code=code)
                creds = flow.credentials
                # Clean up verifier file
                try:
                    vf = HERMES / "calendar" / "flow_verifier.pkl"
                    if vf.exists():
                        vf.unlink()
                except Exception:
                    pass
            else:
                raise RuntimeError("No auth code provided. Run again with the code.")

        # Save token
        TOKEN_FILE.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def get_event_prep(event_id):
    """Fetch event details for prep info."""
    try:
        service = get_calendar_service()
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
        return {
            "attendees": [a.get("email", "") for a in event.get("attendees", [])],
            "description": event.get("description", ""),
            "attachments": [a.get("title", "") for a in event.get("attachments", [])],
        }
    except Exception:
        return {}

def fetch_events(service, time_min=None, time_max=None, max_results=20):
    """Fetch events from primary calendar."""
    if time_min is None:
        time_min = datetime.now(timezone.utc).isoformat()
    if time_max is None:
        time_max = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return events_result.get("items", [])


def parse_event_time(event):
    """Extract start/end datetime from event object."""
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))
    return start, end


def format_event(event):
    """Format a calendar event into a readable string."""
    summary = event.get("summary", "(no title)")
    start, end = parse_event_time(event)
    location = event.get("location", "")
    description = event.get("description", "")

    # Parse time
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        time_str = start_dt.strftime("%H:%M")
        end_str = end_dt.strftime("%H:%M")
        duration = (end_dt - start_dt).total_seconds() / 60

        # Check if all-day
        if duration >= 1440 and start_dt.hour == 0:
            time_str = "All day"
            end_str = ""
        else:
            time_str = f"{start_dt.strftime('%I:%M %p').lstrip('0')} - {end_dt.strftime('%I:%M %p').lstrip('0')}"
    except Exception:
        time_str = start
        end_str = ""
        duration = 0

    parts = [f"  \u2022 {time_str}  {summary}"]
    if location:
        parts.append(f"         @ {location}")
    if description:
        # Extract first line of description
        desc_line = description.split("\n")[0][:80]
        parts.append(f"         {desc_line}")

    return "\n".join(parts)


def get_today_events(service=None):
    """Get today's events."""
    if service is None:
        service = get_calendar_service()

    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    events = fetch_events(service,
                          time_min=day_start.isoformat(),
                          time_max=day_end.isoformat())

    return events


def get_upcoming_events(service=None, days=7):
    """Get events for the next N days."""
    if service is None:
        service = get_calendar_service()

    now = datetime.now(timezone.utc)
    future = now + timedelta(days=days)

    return fetch_events(service,
                        time_min=now.isoformat(),
                        time_max=future.isoformat())


def cache_events():
    """Fetch and cache events for quick access by other scripts."""
    try:
        service = get_calendar_service()
        today = get_today_events(service)
        upcoming = get_upcoming_events(service, days=7)

        cache = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "today": [
                {
                    "summary": e.get("summary"),
                    "start": parse_event_time(e)[0],
                    "end": parse_event_time(e)[1],
                    "location": e.get("location", ""),
                }
                for e in today
            ],
            "upcoming": [
                {
                    "summary": e.get("summary"),
                    "start": parse_event_time(e)[0],
                    "end": parse_event_time(e)[1],
                    "location": e.get("location", ""),
                }
                for e in upcoming[:20]
            ],
        }

        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, indent=2))
        print(f"Cached {len(today)} today, {len(upcoming)} upcoming")
    except Exception as e:
        print(f"Cache error: {e}")


def generate_briefing_section():
    """Generate a calendar-aware section for the morning briefing."""
    try:
        if CACHE_FILE.exists():
            cache = json.loads(CACHE_FILE.read_text())
        else:
            cache_events()
            cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {"today": [], "upcoming": []}

        today = cache.get("today", [])
        upcoming = cache.get("upcoming", [])

        lines = []
        if today:
            # Separate ongoing vs upcoming
            now = datetime.now(timezone.utc)
            upcoming_today = []
            ongoing = []
            for e in today:
                try:
                    start = datetime.fromisoformat(e["start"])
                    end = datetime.fromisoformat(e["end"])
                    if start <= now <= end:
                        ongoing.append(e)
                    elif start > now:
                        upcoming_today.append(e)
                except Exception:
                    upcoming_today.append(e)

            if ongoing:
                lines.append(f"  Right now: {ongoing[0]['summary']}")

            if upcoming_today:
                lines.append(f"  Today's agenda:")
                for e in upcoming_today[:5]:
                    try:
                        start = datetime.fromisoformat(e["start"]).strftime("%I:%M %p").lstrip("0")
                        lines.append(f"    \u2022 {start} - {e['summary']}")
                    except Exception:
                        lines.append(f"    \u2022 {e['summary']}")
        else:
            lines.append("  No events on your calendar today.")

        # Next few days
        future = [e for e in upcoming if e not in today][:3]
        if future:
            lines.append(f"  Coming up:")
            for e in future:
                try:
                    start = datetime.fromisoformat(e["start"])
                    day = start.strftime("%a")
                    time = start.strftime("%I:%M %p").lstrip("0")
                    lines.append(f"    \u2022 {day} {time} - {e['summary']}")
                except Exception:
                    lines.append(f"    \u2022 {e['summary']}")

        return "\n".join(lines) if lines else "  Calendar: check your Google Calendar."

    except Exception as e:
        return f"  Calendar: could not fetch ({e})"


def check_upcoming_reminders(minutes_before=15):
    """Check if any event is starting within minutes_before and send reminder."""
    try:
        service = get_calendar_service()
        now = datetime.now(timezone.utc)
        soon = now + timedelta(minutes=minutes_before)

        events = fetch_events(service,
                              time_min=now.isoformat(),
                              time_max=soon.isoformat(),
                              max_results=5)

        for event in events:
            start, _ = parse_event_time(event)
            try:
                start_dt = datetime.fromisoformat(start)
                mins_until = (start_dt - now).total_seconds() / 60
                if 0 <= mins_until <= minutes_before:
                    summary = event.get("summary", "Untitled")
                    loc = event.get("location", "")
                    msg = f"Reminder: {summary} in {int(mins_until)} min"
                    if loc:
                        msg += f" @ {loc}"
                    send(msg)
            except Exception:
                pass
    except Exception as e:
        print(f"Reminder check error: {e}")


def next_event_text() -> str:
    """Return a one-line summary of the next event (for persona_engine)."""
    try:
        if CACHE_FILE.exists():
            cache = json.loads(CACHE_FILE.read_text())
            all_events = cache.get("today", []) + cache.get("upcoming", [])
            now = datetime.now(timezone.utc)
            for e in all_events:
                try:
                    start = datetime.fromisoformat(e["start"])
                    if start > now:
                        mins = int((start - now).total_seconds() / 60)
                        if mins < 60:
                            return f"Next: {e['summary']} in {mins} min"
                        else:
                            return f"Next: {e['summary']} at {start.strftime('%I:%M %p').lstrip('0')}"
                except Exception:
                    pass
        return ""
    except Exception:
        return ""


# ─── Write-capable authoring (OAuth: calendar.events) ────────────────────

def create_event(
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str | None = None,
    attendees: list[str] | None = None,
    reminders: bool = True,
) -> dict:
    """Create a Google Calendar event and return the API response."""
    service = get_calendar_service()
    event = {
        "summary": summary,
        "start": {"dateTime": start_iso, "timeZone": "UTC"},
        "end": {"dateTime": end_iso, "timeZone": "UTC"},
    }
    if description:
        event["description"] = description
    if attendees:
        event["attendees"] = [{"email": a} for a in attendees]
    if reminders:
        event["reminders"] = {"useDefault": False, "overrides":
                              [{"method": "email", "minutes": 15}]}
    return service.events().insert(calendarId="primary", body=event).execute()


def propose_event(title: str, when_iso: str, duration_min: int = 30,
                  description: str | None = None) -> dict:
    """Propose a calendar event (non-confirming — caller must confirm via Telegram)."""
    from datetime import timedelta
    start = datetime.fromisoformat(when_iso.replace("Z", "+00:00"))
    end = start + timedelta(minutes=duration_min)
    return {
        "proposed": True,
        "summary": title,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "description": description or "",
        "confirm_cmd": f"/calendar-create \"{title}\" {start.isoformat()}",
    }


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]

    if "--cache" in args:
        cache_events()
    elif "--today" in args:
        try:
            service = get_calendar_service()
            events = get_today_events(service)
            for e in events:
                print(format_event(e))
        except RuntimeError as e:
            print(f"AUTH NEEDED: {e}")
            send(f"Calendar auth needed — run: python3 calendar_intelligence.py --auth")
    elif "--remind" in args:
        check_upcoming_reminders()
    elif "--prep" in args:
        # Show upcoming event with prep details
        event = next_event_text()
        if event and "No events" not in event:
            print(event)
            print("\nPrep (next meeting):")
            # Fetch next event ID for prep
            try:
                service = get_calendar_service()
                now = datetime.now(timezone.utc).isoformat()
                upcoming = service.events().list(calendarId="primary", timeMin=now, maxResults=1, 
                                                  orderBy="startTime", singleEvents=True).execute()
                if upcoming.get("items"):
                    eid = upcoming["items"][0].get("id")
                    prep = get_event_prep(eid)
                    if prep.get("attendees"):
                        print(f"  Attendees: {', '.join(prep['attendees'][:3])}")
                    if prep.get("description"):
                        print(f"  Agenda: {prep['description'][:200]}")
            except Exception as ex:
                print(f"  Could not fetch prep: {ex}")
    
    elif "--next" in args:
        print(next_event_text())
    elif "--prep" in args:
        print(next_event_text())
        try:
            service = get_calendar_service()
            now = datetime.now(timezone.utc).isoformat()
            upcoming = service.events().list(calendarId="primary", timeMin=now, maxResults=1,
                                              orderBy="startTime", singleEvents=True).execute()
            if upcoming.get("items"):
                eid = upcoming["items"][0].get("id")
                if eid:
                    prep = get_event_prep(eid)
                    if prep.get("attendees"):
                        print(f"  Attendees: {', '.join(prep['attendees'][:3])}")
                    if prep.get("description"):
                        print(f"  Agenda: {prep['description'][:200]}")
        except Exception:
            pass


        print(next_event_text())
    elif "--brief" in args:
        print(generate_briefing_section())
    elif "--auth" in args:
        # Force auth flow
        print("Starting OAuth for Google Calendar...")
        try:
            service = get_calendar_service()
            print("Auth successful! Token saved.")
            cache_events()
        except RuntimeError as e:
            if "No auth code provided" in str(e):
                print("Waiting for auth code. Paste it now:")
                code = sys.stdin.readline().strip()
                if code:
                    # Re-run auth with the code via env var
                    os.environ["HERMES_AUTH_CODE"] = code
                    service = get_calendar_service()
                    print("Auth successful! Token saved.")
                    cache_events()
            else:
                raise
    else:
        cache_events()
