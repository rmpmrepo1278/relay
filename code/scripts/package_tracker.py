#!/usr/bin/env python3
"""package_tracker.py — Track packages from Gmail.

Scans inbox for tracking numbers in any email (no sender whitelist),
extracts tracking info, and reports status.

Usage:
    python3 package_tracker.py scan       # Scan Gmail, update state, show results
    python3 package_tracker.py status     # Show current tracked packages
    python3 package_tracker.py alert      # Scan and send Telegram alerts for changes
    python3 package_tracker.py --daemon   # One-shot for cron (alert + exit)
"""

from __future__ import annotations
import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

HERMES_HOME = Path.home() / ".hermes"
STATE_FILE = HERMES_HOME / "data" / "packages.json"
TELEGRAM_BOT_TOKEN = None
TELEGRAM_CHAT_ID = None

# ── Known forwarders — emails from these addresses are scanned for
#    forwarded/original shipping confirmations in the body.
KNOWN_FORWARDERS = [
    "sunayana.kar@gmail.com",
]

CARRIERS = {
    "fedex": {
        "patterns": [r"\b(\d{12,15})\b", r"\b(F\d{12})\b"],
        "url": "https://www.fedex.com/fedextrack/?trknbr={}",
        "name": "FedEx",
    },
    "ups": {
        "patterns": [r"\b(1Z[0-9A-Z]{16})\b"],
        "url": "https://www.ups.com/track?tracknum={}",
        "name": "UPS",
    },
    "usps": {
        "patterns": [
            r"\b(94\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2})\b",
            r"\b(\d{20,22})\b",
        ],
        "url": "https://tools.usps.com/go/TrackConfirmAction?tLabels={}",
        "name": "USPS",
    },
    "dhl_express": {
        "patterns": [r"\b(\d{10})\b"],
        "url": "https://www.dhl.com/en/express/tracking.html?AWB={}",
        "name": "DHL Express",
    },
    "dhl_ecommerce": {
        "patterns": [r"\b(\d{10,12})\b"],
        "url": "https://track.dhlecommerce.com/tracking/?AWB={}",
        "name": "DHL eCommerce",
    },
    "amazon": {
        "patterns": [
            r"\b(T\d{3}-\d{7}-\d{4})\b",
            r"\b(\d{3}-\d{7}-\d{4})\b",
            r"(amazon\.com/gp/your-account/order-details\?orderID=([A-Z0-9-]+))",
            r"(amazon\.in/gp/your-account/order-details\?orderID=([A-Z0-9-]+))",
        ],
        "url": None,
        "name": "Amazon",
    },
    "canada_post": {
        "patterns": [r"\b([A-Za-z]{2}\d{9}[A-Za-z]{2})\b"],
        "url": "https://www.canadapost-postescanada.ca/track-reperage/track/trackAction.do?trackingNumber={}",
        "name": "Canada Post",
    },
    "royal_mail": {
        "patterns": [r"\b([A-Za-z]{2}\d{9}GB)\b"],
        "url": "https://www.royalmail.com/track-your-item#/tracking-results/{}",
        "name": "Royal Mail",
    },
    "australia_post": {
        "patterns": [r"\b(\d{13}[A-Za-z]{2})\b"],
        "url": "https://auspost.com.au/mypost/track/#/details/{}",
        "name": "Australia Post",
    },
    "dpd": {
        "patterns": [r"\b(\d{14})\b"],
        "url": "https://www.dpd.com/tracking/?parcelnumber={}",
        "name": "DPD",
    },
    "hermes_uk": {
        "patterns": [r"\b(\d{16})\b"],
        "url": "https://www.hermesworld.com/tracking/?trackingNumber={}",
        "name": "Hermes UK",
    },
    "lasership": {
        "patterns": [r"\b(L[A-Za-z0-9]{11,15})\b"],
        "url": "https://www.lasership.com/track/{}",
        "name": "LaserShip",
    },
    "ontrac": {
        "patterns": [r"\b(C\d{14})\b", r"\b(\d{10,12})\b"],
        "url": "https://www.ontrac.com/tracking?number={}",
        "name": "OnTrac",
    },
    "aliexpress": {
        "patterns": [r"\b([A-Za-z]{2}\d{9}[A-Za-z]{2})\b", r"\b(\d{13})\b"],
        "url": None,
        "name": "AliExpress",
    },
    "china_post": {
        "patterns": [r"\b([A-Za-z]{2}\d{9}[A-Za-z]{2})\b"],
        "url": None,
        "name": "China Post",
    },
    "singapore_post": {
        "patterns": [r"\b([A-Za-z]{2}\d{7}[A-Za-z]{2})\b"],
        "url": None,
        "name": "Singapore Post",
    },
}


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"packages": [], "last_scan": None}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def _load_env():
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    env_file = HERMES_HOME / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line:
                k, v = line.strip().split("=", 1)
                if k == "TELEGRAM_BOT_TOKEN":
                    TELEGRAM_BOT_TOKEN = v.strip("\"'")
                elif k in ("TELEGRAM_CHAT_ID", "TELEGRAM_HOME_CHANNEL"):
                    TELEGRAM_CHAT_ID = v.strip("'\"")


def _send_telegram(message: str):
    from telegram_bridge import send_telegram_html
    send_telegram_html(message)


def _get_gmail_service():
    """Get Gmail API service using existing Hermes auth."""
    sys.path.insert(0, str(HERMES_HOME / "mcp"))
    try:
        import gmail_server
        if hasattr(gmail_server, "get_service"):
            return gmail_server.get_service()
    except Exception:
        pass
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        for fname in ("token.json", "gmail_token.json", "google_token.json"):
            token_path = HERMES_HOME / fname
            if token_path.exists():
                break
        else:
            token_path = HERMES_HOME / "gmail_token.json"
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path))
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
            return build("gmail", "v1", credentials=creds)
    except Exception as e:
        print(f"Gmail auth failed: {e}", file=sys.stderr)
    return None


def _extract_tracking_numbers(text: str) -> list[dict]:
    """Extract tracking numbers from text using all carrier patterns."""
    found = []
    used_numbers = set()
    for carrier_id, carrier in CARRIERS.items():
        for pattern in carrier["patterns"]:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                num = match.group(1).replace(" ", "")
                if num not in used_numbers and len(num) >= 8:
                    used_numbers.add(num)
                    found.append({
                        "carrier": carrier["name"],
                        "carrier_id": carrier_id,
                        "number": num,
                    })
    return found


def _detect_order_refs(text: str) -> list[str]:
    """Extract Amazon-style order references even without tracking numbers."""
    refs = []
    for m in re.finditer(r"\b(\d{3}-\d{7}-\d{4})\b", text):
        refs.append(m.group(1))
    return refs


def _detect_status_from_text(subject: str, body: str, sender: str) -> Optional[str]:
    """Detect package status from email content."""
    text = (subject + " " + body).lower()
    sender_lower = sender.lower()

    # forwarded email — likely about a shipped/ordered item
    if any(fwd in sender_lower for fwd in KNOWN_FORWARDERS):
        if "delivered" in text:
            return "delivered"
        if "out for delivery" in text:
            return "out_for_delivery"
        if "shipped" in text or "has shipped" in text:
            return "shipped"
        if "in transit" in text:
            return "in_transit"
        if any(w in text for w in ["ordered", "order confirmed", "preparing", "your order"]):
            return "ordered"
        return "forwarded"

    # direct shipping email
    if "delivered" in text or "package was delivered" in text:
        return "delivered"
    if "out for delivery" in text or "out-for-delivery" in text:
        return "out_for_delivery"
    if any(w in text for w in ["shipped", "has shipped", "shipping confirmation", "is on the way"]):
        return "shipped"
    if "in transit" in text or "on the way" in text:
        return "in_transit"
    if any(w in text for w in ["preparing", "preparing to ship", "label created"]):
        return "preparing"
    return None



def _extract_estimated_delivery(subject: str, body: str, status: str = None) -> str:
    """Extract estimated delivery date from email content."""
    from datetime import datetime, timedelta
    import re as _re

    text = (subject + " " + body[:3000]).lower()
    today = datetime.now()
    
    # 1. Check for "out for delivery today" or "arrives today"
    if "today" in text and (
        "out for delivery" in text or
        "arrives today" in text or
        "arriving today" in text or
        "delivery today" in text or
        "by 8 pm" in text or "by 9 pm" in text
    ):
        return today.strftime("%Y-%m-%d")

    # 2. "tomorrow"
    if "tomorrow" in text and (
        "arriving" in text or "arrive" in text or
        "delivery" in text or "delivered" in text or
        "scheduled" in text or "estimated" in text
    ):
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # 3. Specific dates: "July 15, 2026" or "July 15 2026"
    date_patterns = [
        r"(?:delivery|arrive|arriving|by|estimated|scheduled)\s*(?:on|by|for|:)?\s*(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:,?\s*(\d{4}))?",
        r"(?:delivery|arrive|arriving|by|estimated|scheduled)\s*(?:on|by|for|:)?\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})(?:,?\s*(\d{4}))?",
        r"(\d{1,2})/(\d{1,2})/(\d{4})",
        r"(\d{4})-(\d{1,2})-(\d{1,2})",
    ]
    
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    
    for pattern in date_patterns[:2]:  # Month name patterns
        m = _re.search(pattern, text, _re.IGNORECASE)
        if m:
            month_name = m.group(1).lower()
            day = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else today.year
            try:
                d = datetime(year, months[month_name], day)
                if d > today:
                    return d.strftime("%Y-%m-%d")
            except ValueError:
                pass
    
    # 4. "delivery on Friday" / "arrives Tuesday" patterns
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_pattern = r"(?:delivery|arrive|arriving|scheduled|by|estimated)\s*(?:on|by|for|:)?\s*(?:(?:next|this)\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    m = _re.search(day_pattern, text, _re.IGNORECASE)
    if m:
        target_day = m.group(1).lower()
        target_idx = day_names.index(target_day)
        current_idx = today.weekday()
        days_ahead = target_idx - current_idx
        if days_ahead <= 0:
            days_ahead += 7  # Next week
        d = today + timedelta(days=days_ahead)
        return d.strftime("%Y-%m-%d")
    
    # 5. Based on status, provide reasonable estimates
    if status == "out_for_delivery":
        return today.strftime("%Y-%m-%d")
    elif status == "shipped":
        # Shipped items typically arrive in 1-5 days
        return (today + timedelta(days=3)).strftime("%Y-%m-%d")
    elif status in ("ordered", "forwarded"):
        return (today + timedelta(days=7)).strftime("%Y-%m-%d")
    
    return "unknown"



def _get_body_from_payload(payload: dict) -> str:
    """Extract text body from Gmail message payload."""
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            mime = part.get("mimeType", "")
            if mime == "text/plain" and "data" in part.get("body", {}):
                try:
                    body += base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                except Exception:
                    pass
            elif "parts" in part:
                body += _get_body_from_payload(part)
    elif "body" in payload and "data" in payload["body"]:
        try:
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        except Exception:
            pass
    return body


def _is_tracking_related(subject: str, body: str) -> bool:
    """Check if email likely contains tracking/shipping info."""
    subj = subject.lower()
    text = (subj + " " + body[:2000]).lower()
    
    # First check if subject has clear shipping keywords
    subject_keywords = [
        "tracking", "shipped", "shipping", "delivered", "delivery",
        "out for delivery", "in transit", "package", "parcel",
        "order", "confirmation", "dispatch", "shipment",
        "fedex", "ups", "usps", "dhl", "lasership", "amazon",
        "your item", "label created", "order update",
        "order confirmed", "order number", "your order",
        "arrives today", "on the way", "transit",
        "ordered:", "ordered ",
    ]
    has_subject_kw = any(kw in subj for kw in subject_keywords)
    
    # Then check body for shipping signals
    body_keywords = [
        "tracking number", "shipping confirmation", "your package",
        "out for delivery", "delivery today", "in transit",
        "has shipped", "has been delivered", "arrives tomorrow",
    ]
    body_lower = body[:2000].lower()
    has_body_kw = any(kw in body_lower for kw in body_keywords)
    
    # If no shipping keywords at all, reject early
    if not (has_subject_kw or has_body_kw):
        return False
    
    # Hard excludes — only for emails that DON'T have clear subject shipping keywords
    # (e.g., an email subject says "Your order is confirmed" but body mentions Chase = still a package)
    if not has_subject_kw and has_body_kw:
        hard_exclude = [
            "weekly ad", "savings", "fresh tech", "best-selling", "most-loved",
            "streamline your", "you're only one order away",
            "free dominos", "free streaming", "audible for $0.99",
            "rate your transaction", "check out your weekly",
            "introducing our must-have", "so many savings",
            "father.days is tomorrow", "view your weekly ad",
            "take an extra", "start saving now",
            "chase", "credit card", "bonus", "points", "reward",
            "→", "stock", "trading", "portfolio",
            "rejection", "rejected", "explained too much",
        ]
        if any(kw in text for kw in hard_exclude):
            return False
    
    return has_subject_kw or has_body_kw


def scan_gmail(days: int = 90) -> list[dict]:
    """Scan Gmail inbox for shipping/tracking emails from any sender."""
    import sys as _sys
    service = _get_gmail_service()
    if not service:
        print("Gmail service unavailable", file=_sys.stderr)
        return []
    print(f"Scanning Gmail (last {days}d, 3 queries)...", file=_sys.stderr)

    # Scan broadly — tracking-related keywords across inbox
    # Use multiple queries to catch everything
    base_queries = [
        f"(tracking OR shipped OR delivered OR 'in transit' OR 'out for delivery') newer_than:{days}d",
        f"(from:amazon OR from:fedex OR from:ups OR from:usps OR from:dhl) newer_than:{days}d",
    ]
    # Forwarders — include their emails too
    if KNOWN_FORWARDERS:
        fwd_query = " OR ".join(f"from:{f}" for f in KNOWN_FORWARDERS)
        base_queries.append(f"({fwd_query}) newer_than:{days}d")

    seen_ids = set()
    found_packages = []

    for qi, query in enumerate(base_queries, 1):
        print(f"  Query {qi}/{len(base_queries)}...", file=_sys.stderr)
        try:
            results = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
        except Exception as e:
            print(f"  Query {qi} failed: {e}", file=_sys.stderr)
            continue
        msgs = results.get("messages", [])
        print(f"  Query {qi} returned {len(msgs)} messages", file=_sys.stderr)

        for msg in results.get("messages", []):
            msg_id = msg["id"]
            if msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)

            try:
                msg_data = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
            except Exception as e:
                print(f"Error fetching {msg_id}: {e}", file=_sys.stderr)
                continue

            headers = {h["name"]: h["value"] for h in msg_data["payload"]["headers"]}
            subject = headers.get("Subject", "")
            sender = headers.get("From", "")
            date_str = headers.get("Date", "")
            body = _get_body_from_payload(msg_data["payload"])

            text = subject + " " + body

            # Extract tracking numbers
            tracking_numbers = _extract_tracking_numbers(text)
            order_refs = _detect_order_refs(text) if not tracking_numbers else []
            email_status = _detect_status_from_text(subject, body, sender)

            # Skip pure marketing emails regardless of tracking numbers
            subject_lower = subject.lower()
            sender_lower = sender.lower()
            marketing_kw = [
                "weekly ad", "fresh tech", "best-selling", "most-loved",
                "streamline your", "start saving now",
                "free streaming", "audible for", "rate your transaction",
                "so many savings", "take an extra", "view your weekly",
                "you're only one order away", "free dominos"
            ]
            # Also block known promotional sender domains
            promo_domains = ["eml.walgreens.com", "ecomm.lenovo.com", "store-news@amazon.com",
                             "e-rewards.dominos.com", "business.amazon.com"]
            is_marketing = any(kw in subject_lower for kw in marketing_kw)
            is_promo_sender = any(d in sender_lower for d in promo_domains)
            if (is_marketing or is_promo_sender) and not any(fwd in sender_lower for fwd in KNOWN_FORWARDERS):
                continue
            
            # Only process if it has tracking numbers, order refs, or looks shipping-related
            has_tracking = bool(tracking_numbers)
            has_order_ref = bool(order_refs)
            is_forwarder = any(fwd in sender.lower() for fwd in KNOWN_FORWARDERS)
            is_shipping_related = _is_tracking_related(subject, body)

            if not (has_tracking or has_order_ref or is_forwarder or is_shipping_related):
                continue

            # Double-check even tracked emails against non-package filter
            if has_tracking and not _is_tracking_related(subject, body):
                continue  # tracking numbers found but email is clearly marketing/non-package

            # For forwarders, only include if it looks like a real shipment/package
            original_sender = sender
            if is_forwarder:
                # Skip clearly non-package forwards
                non_package_kw = [
                    "library", "tax form", "rent payment", "membership has been canceled",
                    "thank you for your payment", "flight credit", "eye exam",
                    "you.re invited", "register for", "fidelity", "income tax",
                    "willow tv", "cinemark subscription", "eticket", "itinerary",
                    "japan trip", "extra 20% off your first", "window cleaning",
                    "free tv", "better than cable", "onboarding", "case ",
                    "wee", "delivery confirmed"
                ]
                subj_lower = subject.lower()
                if not subject or len(subject.strip()) < 5:
                    continue  # skip — empty/minimal subject
                if any(kw in subj_lower for kw in non_package_kw):
                    continue  # skip — not a package

                # Look for "Begin forwarded message:" pattern
                fwd_match = re.search(
                    r"Begin forwarded message[:：][\s\S]*?From:\s*([^\n]+)",
                    body, re.IGNORECASE
                )
                if fwd_match:
                    original_sender = fwd_match.group(1).strip()

            if has_tracking:
                for tn in tracking_numbers:
                    pkg = {
                        "number": tn["number"],
                        "carrier": tn["carrier"],
                        "carrier_id": tn["carrier_id"],
                        "status": email_status or "unknown",
                        "source": original_sender,
                        "subject": subject[:100],
                        "date_found": date_str,
                        "last_updated": datetime.now(timezone.utc).isoformat(),
                        "notified": False,
                        "forwarded_by": sender if is_forwarder else None,
                        "estimated_delivery": _extract_estimated_delivery(subject, body, email_status),
                    }
                    found_packages.append(pkg)
            else:
                # No tracking number but shipping-related email
                pkg = {
                    "number": None,
                    "carrier": "unknown",
                    "carrier_id": "unknown",
                    "status": email_status or "unknown",
                    "source": original_sender,
                    "subject": subject[:100],
                    "date_found": date_str,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "notified": False,
                    "forwarded_by": sender if is_forwarder else None,
                    "order_refs": order_refs,
                    "estimated_delivery": _extract_estimated_delivery(subject, body, email_status),
                }
                found_packages.append(pkg)

    print(f"  Done — {len(found_packages)} packages extracted", file=_sys.stderr)

    # Filter out garbage tracking numbers (HTML/JSON artifacts)
    clean = []
    garbage_patterns = [
        r"^lastListItem$", r"^labelValue", r"^linkStyledText", r"^littlecaesars",
        r"^undefined$", r"^null$", r"^true$", r"^false$",
    ]
    for pkg in found_packages:
        num = pkg.get("number", "")
        if num:
            is_garbage = False
            for gp in garbage_patterns:
                if re.match(gp, num, re.IGNORECASE):
                    is_garbage = True
                    break
            if is_garbage:
                continue
        # Skip pure marketing emails that match no real tracking context
        subj = pkg.get("subject", "").lower()
        marketing_kw = ["weekly ad", "savings", "fresh tech", "best-selling", "most-loved",
                        "streamline your business", "prime day", "you're only one order away",
                        "free dominos", "free streaming", "audible for", "rate your transaction"]
        if not pkg.get("number") and not pkg.get("forwarded_by"):
            # Only skip if it's a marketing email without tracking number
            pass  # keep delivered items and order confirmations
        clean.append(pkg)

    print(f"  Filtered {len(found_packages) - len(clean)} garbage entries", file=_sys.stderr)
    return clean


def merge_packages(new_packages: list[dict], existing: list[dict]) -> list[dict]:
    """Merge new scan results with existing state.
    Groups multiple tracking numbers from the same email into one package entry."""
    # First, group new packages by (sender, subject) to combine multi-tracking emails
    email_groups = {}
    for pkg in new_packages:
        key = (pkg.get("source", "")[:60], pkg.get("subject", "")[:60])
        if key not in email_groups:
            email_groups[key] = pkg
            # Collect all tracking numbers
            email_groups[key]["_all_numbers"] = []
        if pkg.get("number") and pkg["number"] not in email_groups[key].get("_all_numbers", []):
            email_groups[key].setdefault("_all_numbers", []).append(pkg["number"])
            # Use the first meaningful tracking number (not date-like) as primary
            if not email_groups[key].get("number") or                (len(email_groups[key]["number"]) == 14 and email_groups[key]["number"][:8].isdigit()):
                # Skip date-like numbers (14 digits starting with date)
                if not (len(pkg["number"]) == 14 and pkg["number"][:8].isdigit()):
                    email_groups[key]["number"] = pkg["number"]
                    email_groups[key]["carrier"] = pkg["carrier"]
                    email_groups[key]["carrier_id"] = pkg["carrier_id"]
            # Pick best status
            status_rank = {"out_for_delivery": 5, "delivered": 4, "in_transit": 3, "shipped": 2, "ordered": 1, "unknown": 0}
            if status_rank.get(pkg.get("status", ""), 0) > status_rank.get(email_groups[key].get("status", ""), 0):
                email_groups[key]["status"] = pkg["status"]

    grouped_new = list(email_groups.values())
    # Remove _all_numbers helper, add tracking count
    for pkg in grouped_new:
        all_nums = pkg.pop("_all_numbers", [])
        pkg["_tracking_count"] = len(all_nums)

    # Now merge with existing
    existing_map = {}
    for pkg in existing:
        key = pkg.get("number") or pkg.get("subject", "")[:50]
        existing_map[key] = pkg

    for pkg in grouped_new:
        key = pkg.get("number") or pkg.get("subject", "")[:50]
        if key in existing_map:
            old_status = existing_map[key].get("status")
            if old_status != pkg["status"]:
                pkg["notified"] = False
            pkg["date_found"] = existing_map[key].get("date_found", pkg["date_found"])
            if not pkg["notified"]:
                pkg["notified"] = existing_map[key].get("notified", False)

    def _pkg_key(pkg):
        num = pkg.get("number")
        if num:
            return num
        carrier = pkg.get("carrier_id", "unknown")
        subj = pkg.get("subject", "")[:50]
        return f"{carrier}:{subj}"

    merged = {}
    for pkg in existing:
        merged[_pkg_key(pkg)] = pkg
    for pkg in grouped_new:
        key = _pkg_key(pkg)
        if key in merged:
            old = merged[key]
            if old.get("status") != pkg.get("status"):
                pkg["notified"] = False
            pkg["date_found"] = old.get("date_found", pkg["date_found"])
            if not pkg["notified"]:
                pkg["notified"] = old.get("notified", False)
        merged[key] = pkg

    result = list(merged.values())
    result.sort(key=lambda x: x.get("date_found", ""), reverse=True)
    return result


def try_update_status(packages: list[dict]) -> list[dict]:
    """Try to fetch live status from carrier websites (max 50 attempts, 5s timeout)."""
    import sys as _sys
    updated = []
    attempts = 0
    max_attempts = 8
    for pkg in packages:
        if pkg.get("status") in ("delivered", "out_for_delivery"):
            updated.append(pkg)
            continue
        if attempts >= max_attempts:
            updated.append(pkg)
            continue
        if not pkg.get("number") or len(pkg.get("number", "")) < 8:
            updated.append(pkg)
            continue
        attempts += 1
        if attempts % 10 == 1:
            print(f"  Fetching live status ({attempts}/{max_attempts})...", file=_sys.stderr)
        live_status = _fetch_carrier_status(pkg, timeout=5)
        if live_status and live_status != pkg.get("status"):
            pkg["status"] = live_status
            pkg["notified"] = False
            pkg["last_updated"] = datetime.now(timezone.utc).isoformat()
        updated.append(pkg)
    return updated


def _fetch_carrier_status(pkg: dict, timeout: int = 10) -> Optional[str]:
    """Try to fetch tracking status from carrier website. Updates pkg in-place with estimated_delivery."""
    carrier = pkg.get("carrier_id", "").lower()
    number = pkg.get("number", "")
    if not number or carrier in ("amazon", "aliexpress", "china_post", "singapore_post", "unknown"):
        return None
    url = CARRIERS.get(carrier, {}).get("url", "").format(number)
    if not url:
        return None
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(separator=" ", strip=True).lower()
        
        # Extract estimated delivery from carrier page
        est = _extract_estimated_delivery("", text)
        if est and est != "unknown":
            pkg["estimated_delivery"] = est
        
        if "delivered" in text:
            return "delivered"
        if "out for delivery" in text:
            return "out_for_delivery"
        if "in transit" in text or "on the way" in text:
            return "in_transit"
        if "picked up" in text:
            return "picked_up"
        if "label created" in text or "shipment created" in text:
            return "label_created"
        return "unknown"
    except Exception:
        return None


def get_alerts(state: dict) -> list[str]:
    alerts = []
    for pkg in state.get("packages", []):
        if pkg.get("notified"):
            continue
        status = pkg.get("status", "unknown")
        carrier = pkg.get("carrier", "Unknown")
        number = pkg.get("number") or ""
        subject = pkg.get("subject", "")

        # Skip false positives: no tracking number and no carrier
        if not number and (carrier == "unknown" or carrier == "Unknown"):
            # Mark as notified to prevent re-processing
            pkg["notified"] = True
            pkg["skipped"] = True
            continue

        display_num = number if number else "no tracking #"

        if status == "delivered":
            alerts.append(f"📦 <b>{carrier}</b> — package delivered! {display_num}")
        elif status == "out_for_delivery":
            alerts.append(f"📦 <b>{carrier}</b> — out for delivery! {number}")
        elif status == "in_transit":
            alerts.append(f"📦 <b>{carrier}</b> — in transit: {number}")
        elif status == "shipped" and not pkg.get("notified"):
            alerts.append(f"📦 <b>{carrier}</b> — shipped: {subject[:80]}")
        elif status == "forwarded":
            alerts.append(f"📦 Forwarded: {subject[:80]}")
    return alerts


def run_scan(fetch_live: bool = False, send_alerts: bool = False) -> dict:
    _load_env()
    state = _load_state()

    new_packages = scan_gmail(days=90)
    if new_packages:
        state["packages"] = merge_packages(new_packages, state.get("packages", []))

    if fetch_live:
        state["packages"] = try_update_status(state["packages"])

    state["last_scan"] = datetime.now(timezone.utc).isoformat()

    alerts = get_alerts(state)
    for pkg in state["packages"]:
        for alert_msg in alerts:
            if pkg.get("number") and str(pkg.get("number")) in alert_msg:
                pkg["notified"] = True
            elif pkg.get("subject", "")[:50] in alert_msg:
                pkg["notified"] = True

    _save_state(state)
    return {"packages": state["packages"], "alerts": alerts, "total": len(state["packages"])}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "scan":
        fetch_live = "--live" in sys.argv
        result = run_scan(fetch_live=fetch_live, send_alerts=False)
        print(json.dumps(result, indent=2, default=str))
        pkgs = result.get("packages", [])
        delivered = sum(1 for p in pkgs if p.get("status") == "delivered")
        in_transit = sum(1 for p in pkgs if p.get("status") in ("in_transit", "out_for_delivery", "shipped", "preparing"))
        print(f"\n{result['total']} packages tracked. {delivered} delivered, {in_transit} in transit.")

    elif cmd == "status":
        state = _load_state()
        if not state.get("packages"):
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print("📦 PACKAGE TRACKER — NO PACKAGES TRACKED")
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print("Zero packages found in inbox (last 90 days).")
            print("If you expected something, try 'python3 package_tracker.py scan'")
            print("to re-scan Gmail for tracking numbers.")
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"📦 PACKAGE TRACKER — {len(state['packages'])} PACKAGE(S)")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        from collections import Counter as _Counter
        from datetime import datetime as _dt, date as _date
        today = _date.today()
        for pkg in state["packages"]:
            status = pkg.get("status", "?").replace("_", " ")
            carrier = pkg.get("carrier", "?")
            number = pkg.get("number") or "no tracking #"
            src = pkg.get("source", "?")
            subj = pkg.get("subject", "")[:60]
            fwd = pkg.get("forwarded_by", "")
            tc = pkg.get("_tracking_count", 1)
            ed = pkg.get("estimated_delivery", "")
            print(f"  Status: {status}")
            print(f"  Carrier: {carrier}")
            if tc > 1:
                print(f"  Tracking: {number} (+{tc-1} more)")
            else:
                print(f"  Tracking: {number}")
            print(f"  Item: {subj}")
            if ed and ed != "unknown" and status not in ("delivered",):
                try:
                    ed_date = _dt.strptime(ed, "%Y-%m-%d").date()
                    if ed_date == today:
                        label = "TODAY"
                    elif ed_date == today.replace(day=today.day + 1):
                        label = "tomorrow"
                    else:
                        days = (ed_date - today).days
                        label = ed_date.strftime("%a %b %d") + (f" (in {days}d)" if days > 0 else "")
                    print(f"  Estimated delivery: {label}")
                except ValueError:
                    print(f"  Estimated delivery: {ed}")
            print(f"  From: {src}")
            if fwd:
                print(f"  Forwarded by: {fwd}")
            print("  ---")
        print(f"Total: {len(state['packages'])} package(s)")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    elif cmd == "alert":
        result = run_scan(fetch_live=True, send_alerts=True)
        alerts = result.get("alerts", [])
        if alerts:
            msg = "\n\n".join(alerts)
            _send_telegram(f"📦 <b>Package Updates</b>\n\n{msg}")
            print(f"Sent {len(alerts)} alerts")
        else:
            print("No new alerts")

    elif cmd == "--daemon":
        # Scan Gmail (daily) + live status + alerts
        state = _load_state()
        last_scan = state.get("last_scan", "")
        hours_since_scan = 999
        if last_scan:
            try:
                from datetime import datetime
                last = datetime.fromisoformat(last_scan)
                hours_since_scan = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            except:
                pass
        
        # Only re-scan Gmail if last scan was > 12 hours ago
        if hours_since_scan > 12:
            result = run_scan(fetch_live=True, send_alerts=True)
            alerts = result.get("alerts", [])
        else:
            # Just check existing state + live updates (active packages only)
            state = _load_state()
            pkgs = state.get("packages", [])
            # Only fetch live status for high-priority packages (out for delivery, in transit, shipped)
            priority_statuses = ("out_for_delivery", "in_transit", "shipped")
            active = [p for p in pkgs if p.get("status") in priority_statuses and p.get("number") and len(p.get("number","")) >= 8]
            updated = try_update_status(active)
            # Merge updated statuses back
            updated_map = {}
            for p in updated:
                n = p.get("number", "")
                if n:
                    updated_map[n] = p.get("status")
            for p in pkgs:
                n = p.get("number", "")
                if n in updated_map and updated_map[n] != p.get("status"):
                    p["status"] = updated_map[n]
                    p["notified"] = False
                    p["last_updated"] = datetime.now(timezone.utc).isoformat()
            alerts = get_alerts({"packages": pkgs})
            for pkg in pkgs:
                for alert_msg in alerts:
                    if pkg.get("number") and str(pkg.get("number")) in alert_msg:
                        pkg["notified"] = True
                    elif pkg.get("subject", "")[:50] in alert_msg:
                        pkg["notified"] = True
            state["packages"] = pkgs
            _save_state(state)
            result = {"total": len(pkgs), "alerts": alerts}
        
        if alerts:
            msg = "\n\n".join(alerts)
            _send_telegram(f"📦 <b>Package Updates</b>\n\n{msg}")
        print(f"Daemon: {result['total']} packages, {len(alerts)} alerts (last scan: {hours_since_scan:.0f}h ago)")

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
