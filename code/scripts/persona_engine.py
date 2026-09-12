#!/usr/bin/env python3
"""persona_engine.py — Hermes personality layer.

Generates context-aware, personality-rich messages for Telegram.
Reads interest profile, system state, journal, time of day,
and produces messages that feel like they come from a real person.
"""

import json
import random
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path.home() / ".hermes"

def should_use_calendar():
    """Gate: decide if we need calendar context (skip if no meetings soon)."""
    from datetime import datetime, timezone, timedelta
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    
    try:
        creds = Credentials.from_authorized_user_file(
            str(HERMES / "calendar" / "token.json"),
            ["https://www.googleapis.com/auth/calendar.readonly"]
        )
        service = build("calendar", "v3", credentials=creds)
        now = datetime.now(timezone.utc).isoformat()
        soon = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        events = service.events().list(calendarId="primary", timeMin=now, timeMax=soon, maxResults=5).execute()
        return len(events.get("items", [])) > 0
    except Exception:
        return False

SIGNATURES = ["~Hermes", "--Hermes", "~h", "--h"]

MORNING_OPENERS = [
    "Morning. Here's what I've got before you dive in:",
    "Rise and shine. Your homelab survived the night. Here's the state of things:",
    "Good morning. I've been thinking about",
    "Hey. Been poking around. A few things worth your attention:",
    "The night shift is over. Here's what surfaced:",
]

AFTERNOON_OPENERS = [
    "Checking in mid-day. A few things crossed my desk:",
    "Afternoon update. Some signals worth noting:",
    "Hey — found a few things while you were busy:",
    "Status check. Here's what's happening:",
]

EVENING_OPENERS = [
    "Evening review. Here's how things shook out today:",
    "Winding down. A few things to flag before tomorrow:",
    "Day's almost done. Here's what I'm tracking for tomorrow:",
    "Evening. Quick summary of what happened while you were out:",
]

CURIOSITY_HOOKS = [
    "How's that {project} project going, by the way? Still iterating on it?",
    "Been meaning to ask — any progress on {project}? I've been noodling on related problems.",
    "What's the current state of {project}? I've been seeing some interesting patterns around it.",
    "Question for you: where's your head at with {project} right now?",
    "I keep noticing signals around {project}. Anything new on that front?",
]

OBSERVATIONS = [
    "Noticed you've been digging into {topic} more lately. Interesting shift.",
    "Your interest in {topic} is showing — it's been dominating the signal mix.",
    "Interesting pattern: {topic} has been a recurring theme in your recent activity.",
]

WIT = [
    "Your server closet is still standing, if that's the kind of reassurance you need today.",
    "The containers are contained. As they should be.",
    "Everything that should be running is running. Nothing that shouldn't be is. It's almost suspicious.",
    "I checked on things so you don't have to. You're welcome.",
    "The lab is quiet. Maybe too quiet. (It's fine, I checked.)",
]


def send(text: str):
    try:
        from telegram_bridge import send_telegram
        send_telegram(text[:4096])
    except Exception:
        pass


def read_json(path):
    try:
        p = HERMES / path
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        return None
    return None


def get_interest_profile():
    dp = HERMES / "data" / "interest_profile.json"
    if dp.exists():
        return json.loads(dp.read_text())
    return None


def get_system_state():
    state = {}
    try:
        r = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.split("\n"):
            if line.startswith("Mem:"):
                parts = line.split()
                state["mem"] = {"used": parts[2], "total": parts[1], "pct": parts[3]}
            if line.startswith("Swap:"):
                parts = line.split()
                state["swap"] = {"used": parts[2], "total": parts[1]}
    except Exception:
        pass
    try:
        r = subprocess.run(["df", "-h", "/", "/mnt/usb"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.split("\n"):
            if line.startswith("/dev/nvme"):
                parts = line.split()
                state["disk_root"] = {"pct": parts[4], "avail": parts[3]}
            if "usb" in line or "sda" in line:
                parts = line.split()
                state["disk_usb"] = {"pct": parts[4], "avail": parts[3]}
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["ps", "aux", "--sort=-%mem"],
            capture_output=True, text=True, timeout=5,
        )
        lines = r.stdout.strip().split("\n")[1:6]
        state["top_procs"] = []
        for line in lines:
            parts = line.split(None, 10)
            if len(parts) >= 11:
                state["top_procs"].append({"cmd": parts[10][:40], "mem": parts[3]})
    except Exception:
        pass
    return state


def pick_random(lst):
    return random.choice(lst)


def get_calendar_context():
    """Try to get calendar context, return empty string on failure."""
    if not should_use_calendar():
        return ""
    try:
        import subprocess, sys
        r = subprocess.run(
            [sys.executable, str(Path.home() / ".hermes" / "scripts" / "calendar_intelligence.py"), "--brief"],
            capture_output=True, text=True, timeout=15
        )
        if r.stdout.strip() and "could not fetch" not in r.stdout:
            return r.stdout.strip()
    except Exception:
        pass
    return ""


def generate_checkin(personality="morning"):
    now = datetime.now(timezone.utc)
    hour = now.hour
    profile = get_interest_profile()
    state = get_system_state()

    if personality == "auto":
        personality = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"

    uses_system = random.random() < 0.4
    uses_curiosity = random.random() < 0.5
    uses_wit = random.random() < 0.3

    lines = []
    topic_hook = profile.get("dominant", "infrastructure").replace("_", " ") if profile else "infrastructure"

    if personality == "morning":
        opener = pick_random(MORNING_OPENERS)
        lines.append(f"{opener} {topic_hook}.")
    elif personality == "afternoon":
        lines.append(pick_random(AFTERNOON_OPENERS))
    else:
        lines.append(pick_random(EVENING_OPENERS))

    lines.append("")

    if uses_system and state:
        obs_parts = []
        if state.get("mem"):
            mem = state["mem"]
            pct_str = mem.get("pct", "0%").replace(",", ".").replace("%", "")
            try:
                pct = float(pct_str)
            except ValueError:
                pct = 0
            mem_status = "fine" if pct < 70 else "elevated" if pct < 85 else "tight"
            swap_gb = state.get("swap", {}).get("used", "0").replace(",", ".")
            obs_parts.append(f"Memory: {mem_status} ({mem['used']}/{mem['total']}, swap {swap_gb}GiB)")
        if state.get("disk_root"):
            obs_parts.append(f"Disk root: {state['disk_root']['pct']}")
        if state.get("top_procs"):
            t = state["top_procs"][0]
            obs_parts.append(f"Top draw: {t['cmd']} ({t['mem']}%)")
        if obs_parts:
            lines.append("  \u2022 " + " \u2014 ".join(obs_parts))
            lines.append("")

    # Calendar section
    cal = get_calendar_context()
    if cal:
        lines.append(cal)
        lines.append("")

    if uses_curiosity and profile:
        domain = profile.get("dominant", "self_hosting")
        project = domain.replace("_", " ").title()
        hook = pick_random(CURIOSITY_HOOKS).format(project=project)
        lines.append(hook)
        lines.append("")

    if uses_wit:
        lines.append(pick_random(WIT))
        lines.append("")

    sig = pick_random(SIGNATURES)
    lines.append(f"`{sig}`")

    return "\n".join(lines)


def generate_alert_prefix(alert_text: str) -> str:
    personalities = [
        "Heads up \u2014 this crossed my desk:",
        "Something worth your attention:",
        "Flagging this:",
        "You should know:",
    ]
    pf = random.choice(personalities)
    sig = pick_random(SIGNATURES)
    return f"{pf}\n\n{alert_text.strip()}\n\n`{sig}`"


def generate_evening_reflection():
    now = datetime.now(timezone.utc)
    lines = [f"Night Report \u2014 {now.strftime('%a %b %d, %H:%M')}", ""]
    lines.append("Day's wrap. Here's what I'm carrying forward:")
    lines.append("")

    state = read_json("data/scheduler_state.json")
    if state:
        last_run = state.get("last_run", "")
        if last_run:
            lines.append(f"  \u2022 Last scheduler run: {last_run}")

    profile = get_interest_profile()
    if profile:
        dom = profile.get("dominant", "?")
        lines.append(f"  \u2022 Dominant interest today: {dom}")

    lines.append("")
    lines.append("What's on your mind for tomorrow?")
    lines.append("")
    sig = pick_random(SIGNATURES)
    lines.append(f"`{sig}`")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    if mode == "evening":
        msg = generate_evening_reflection()
    elif mode == "alert":
        alert = sys.argv[2] if len(sys.argv) > 2 else "(no alert text)"
        msg = generate_alert_prefix(alert)
    else:
        msg = generate_checkin(personality=mode)

    if "--dry-run" in sys.argv:
        print(msg)
    else:
        send(msg)
        print(f"Sent {mode} message to Telegram")
