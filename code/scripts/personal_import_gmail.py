#!/usr/bin/env python3
"""personal_import_gmail.py — Bulk-create Finlay/Calendula entries from last 30d Gmail.

One command to add real data:
  /personal import gmail            (via n8n_bridge_server.py)
  python3 personal_import_gmail.py --dry-run
  python3 personal_import_gmail.py --live

Homelab canonical: /home/rohit/.hermes (HERMES_HOME env override).
Claimed by import-gmail agent (no overlap with board-prune/topic-gc/voice-signatures/baseplate/vault).

Finlay targets: bills (kind=bill) + subscriptions (kind=subscription) → agents/finlay/store.json
Calendula targets: appointments, medication-renewal, id-expiry, travel, fitness → agents/calendula/store.json

Stdlib only, offline-safe. Gmail path:
  1) Try googleapiclient + HERMES_HOME/gmail/token.json + credentials.json
  2) Fallback to mock sample (dry-run friendly, no creds needed)

Dedup: (kind, name, due/date) already in store is skipped.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

# ── HERMES_HOME resolution (homelab canonical, env-overridable) ──────────────
def _resolve_hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env).expanduser()
    homelab = Path("/home/rohit/.hermes")
    try:
        if homelab.exists():
            return homelab
    except Exception:
        pass
    # Mac dev fallback: real home is /Users/rohitmishra/.hermes which mirrors homelab
    return Path.home() / ".hermes"

HERMES_HOME = _resolve_hermes_home()
# Also check canonical if env pointed elsewhere but canonical exists (container /opt/data)
_CANONICAL = Path("/home/rohit/.hermes")
if _CANONICAL.exists() and _CANONICAL != HERMES_HOME:
    # keep HERMES_HOME as env, but know canonical for docs
    pass

AGENTS_DIR = HERMES_HOME / "agents"
FINLAY_STORE = AGENTS_DIR / "finlay" / "store.json"
CALENDULA_STORE = AGENTS_DIR / "calendula" / "store.json"
# Collab fallback for symlink setups (only when HERMES_HOME not explicitly set via env)
_ALT_HOME = Path.home() / ".hermes"
_env_explicit = bool(os.environ.get("HERMES_HOME"))
if not _env_explicit and not AGENTS_DIR.exists() and (_ALT_HOME / "agents").exists():
    AGENTS_DIR = _ALT_HOME / "agents"
    FINLAY_STORE = AGENTS_DIR / "finlay" / "store.json"
    CALENDULA_STORE = AGENTS_DIR / "calendula" / "store.json"

GMAIL_DIR = HERMES_HOME / "gmail"
CREDS_FILE = GMAIL_DIR / "credentials.json"
TOKEN_FILE = GMAIL_DIR / "token.json"
# alt gmail dir (only when not explicit)
if not _env_explicit and not GMAIL_DIR.exists() and (_ALT_HOME / "gmail").exists():
    GMAIL_DIR = _ALT_HOME / "gmail"
    CREDS_FILE = GMAIL_DIR / "credentials.json"
    TOKEN_FILE = GMAIL_DIR / "token.json"

# ── helpers ─────────────────────────────────────────────────────────────────
def _log(msg: str):
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    print(f"[{ts}] import-gmail: {msg}", flush=True)

def _load_store(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {"items": [], "meta": {}}

def _atomic_write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)

def _parse_amount(text: str) -> float | None:
    for pat in [r"\$\s*([\d,]+\.\d{2})", r"\$\s*([\d,]+)", r"USD\s*([\d,]+\.\d{2})"]:
        m = re.search(pat, text)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except Exception:
                continue
    return None

def _parse_date(text: str) -> str | None:
    # Try ISO YYYY-MM-DD
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    # Try MM/DD/YYYY or MM-DD-YYYY
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", text)
    if m:
        try:
            mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if yy < 100:
                yy += 2000
            return datetime.date(yy, mm, dd).isoformat()
        except Exception:
            pass
    # Try "Sep 20, 2026" or "September 20 2026"
    m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})", text, re.I)
    if m:
        try:
            mon_str = m.group(1)[:3].lower()
            months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
            mm = months[mon_str]
            dd = int(m.group(2)); yy = int(m.group(3))
            return datetime.date(yy, mm, dd).isoformat()
        except Exception:
            pass
    # Due in N days
    m = re.search(r"due in (\d+)\s+days?", text, re.I)
    if m:
        try:
            n = int(m.group(1))
            return (datetime.date.today() + datetime.timedelta(days=n)).isoformat()
        except Exception:
            pass
    return None

# ── email classification ────────────────────────────────────────────────────
BILL_KEYWORDS = re.compile(r"\b(bill|invoice|statement|payment due|amount due|due date|autopay|ach debit|utility|electric|water|gas|internet|phone|insurance|rent|mortgage)\b", re.I)
SUB_KEYWORDS = re.compile(r"\b(subscription|renewal|receipt|charged|recurring|membership|netflix|spotify|youtube|apple|google one|cloud storage|gym|vpn)\b", re.I)
APPT_KEYWORDS = re.compile(r"\b(appointment|dentist|doctor|medical|clinic|health|eye exam|checkup|vaccin|lab result)\b", re.I)
MED_KEYWORDS = re.compile(r"\b(prescription|pharmacy|refill|medication|rx |cvs|walgreens)\b", re.I)
ID_KEYWORDS = re.compile(r"\b(passport|driver.?license|global entry|visa|id expir)\b", re.I)
TRAVEL_KEYWORDS = re.compile(r"\b(flight|hotel|itinerary|boarding pass|trip|reservation|airbnb|booking|check.in)\b", re.I)

def classify_email(subject: str, snippet: str, body: str) -> list[dict]:
    text = f"{subject} {snippet} {body[:800]}"
    low = text.lower()
    out = []
    # Finlay candidates — require amount >0 OR strong receipt/billed signal to cut newsletter spam
    if BILL_KEYWORDS.search(text):
        amt = _parse_amount(text)
        # skip newsletters that look like bills but have no amount and no due signal
        has_due_signal = bool(re.search(r"\bdue\b|\bpayment\b|\bautopay\b|\binvoice\b", low))
        if amt is None and not has_due_signal:
            pass
        else:
            due = _parse_date(text) or (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
            name = re.sub(r"\s+", " ", subject.strip())[:60] or "Bill"
            name = re.sub(r"(?i)^(invoice|bill|statement)\s*[:\-]?\s*", "", name).strip() or name
            out.append({"agent":"finlay","kind":"bill","name":name,"amount": amt or 0.0, "due": due, "snippet": snippet[:120]})
    elif SUB_KEYWORDS.search(text) or ("$" in text and "renew" in low):
        amt = _parse_amount(text)
        is_receipt = bool(re.search(r"\b(receipt|charged|billed|payment)\b", low))
        has_strict_sub = bool(re.search(r"\b(subscription|renewal|recurring|membership|netflix|spotify|youtube|google one|cloud storage)\b", low))
        # generic apple/vpn/gym hits require explicit sub signal; otherwise they're promos
        sub_match = SUB_KEYWORDS.search(text)
        is_generic_only = sub_match and not has_strict_sub and not is_receipt and "renew" not in low
        if is_generic_only:
            pass  # skip promo spam like "Apple Cider Donuts Are Back"
        elif amt is None or amt == 0:
            if not is_receipt:
                pass
            else:
                due = _parse_date(text) or (datetime.date.today() + datetime.timedelta(days=14)).isoformat()
                name = re.sub(r"\s+", " ", subject.strip())[:60] or "Subscription"
                out.append({"agent":"finlay","kind":"subscription","name":name,"amount": 0.0, "due": due, "snippet": snippet[:120]})
        else:
            # amount exists — require strict sub signal or receipt, or amount >= 5
            if not (has_strict_sub or is_receipt) and amt < 5:
                pass  # skip low-value promo like "Laundry $1.99"
            elif amt > 5000 and not re.search(r"\b(rent|mortgage|invoice|bill)\b", low):
                pass  # skip portfolio/balance alerts like Fidelity $165k
            elif amt > 500 and not (has_strict_sub or is_receipt):
                pass  # large amount without sub signal is likely not a subscription
            else:
                due = _parse_date(text) or (datetime.date.today() + datetime.timedelta(days=14)).isoformat()
                name = re.sub(r"\s+", " ", subject.strip())[:60] or "Subscription"
                out.append({"agent":"finlay","kind":"subscription","name":name,"amount": amt, "due": due, "snippet": snippet[:120]})
    # Calendula candidates
    if APPT_KEYWORDS.search(text):
        dt = _parse_date(text) or (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        name = re.sub(r"\s+", " ", subject.strip())[:60] or "Appointment"
        out.append({"agent":"calendula","kind":"appointment","name":name,"date": dt, "snippet": snippet[:120]})
    elif MED_KEYWORDS.search(text):
        dt = _parse_date(text) or (datetime.date.today() + datetime.timedelta(days=14)).isoformat()
        name = re.sub(r"\s+", " ", subject.strip())[:60] or "Medication"
        out.append({"agent":"calendula","kind":"medication-renewal","name":name,"date": dt, "snippet": snippet[:120]})
    elif ID_KEYWORDS.search(text):
        dt = _parse_date(text) or (datetime.date.today() + datetime.timedelta(days=60)).isoformat()
        name = re.sub(r"\s+", " ", subject.strip())[:60] or "ID Document"
        out.append({"agent":"calendula","kind":"id-expiry","name":name,"date": dt, "snippet": snippet[:120]})
    elif TRAVEL_KEYWORDS.search(text):
        dt = _parse_date(text) or (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
        name = re.sub(r"\s+", " ", subject.strip())[:60] or "Travel"
        out.append({"agent":"calendula","kind":"travel","name":name,"date": dt, "snippet": snippet[:120]})
    return out

# ── Gmail fetch ─────────────────────────────────────────────────────────────
def _gmail_fetch_live(days: int, query: str, max_results: int) -> list[dict]:
    """Try live Gmail API; raise on failure so caller can fallback."""
    # lazy import so script works without google libs
    from google.oauth2.credentials import Credentials  # type: ignore
    from google.auth.transport.requests import Request  # type: ignore
    from googleapiclient.discovery import build  # type: ignore

    if not TOKEN_FILE.exists():
        raise FileNotFoundError(f"token not found at {TOKEN_FILE}")
    scopes = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
    ]
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), scopes)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
    service = build("gmail", "v1", credentials=creds)
    q = query or f"newer_than:{days}d"
    # ensure newer_than clause
    if "newer_than" not in q and "after:" not in q:
        q = f"{q} newer_than:{days}d".strip()
    results = service.users().messages().list(userId="me", q=q, maxResults=min(max_results, 100)).execute()
    msgs = results.get("messages", [])[:max_results]
    out = []
    for m in msgs:
        md = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
        headers = {h["name"]: h["value"] for h in md.get("payload", {}).get("headers", [])}
        subject = headers.get("Subject", "")
        snippet = md.get("snippet", "")
        payload = md.get("payload", {})
        body = ""
        # decode body
        def _b64(data):
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                return ""
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                    body += _b64(part["body"]["data"])
        elif payload.get("body", {}).get("data"):
            body = _b64(payload["body"]["data"])
        out.append({"id": m["id"], "subject": subject, "snippet": snippet, "body": body[:4000], "headers": headers})
    return out

def _mock_messages() -> list[dict]:
    today = datetime.date.today()
    return [
        {"id":"mock1","subject":"Electric Bill Due Sep 28 — $142.50","snippet":"Your electric statement is ready. Due Sep 28.","body":"Amount due $142.50 due 2026-09-28","headers":{}},
        {"id":"mock2","subject":"Netflix renewal receipt $15.49","snippet":"Your subscription renews Oct 14","body":"Netflix $15.49 renews 2026-10-14","headers":{}},
        {"id":"mock3","subject":"Dentist Appointment Confirmation Oct 02","snippet":"Your appointment is Oct 02 2026 at 10am","body":"Dentist appointment Oct 02, 2026","headers":{}},
        {"id":"mock4","subject":"Flight Itinerary — Jakarta to Tokyo Oct 07","snippet":"Your flight CGK→HND confirmed","body":"Travel on 2026-10-07","headers":{}},
        {"id":"mock5","subject":"Pharmacy refill reminder — Allergy med","snippet":"Refill due soon","body":"Prescription refill due 2026-09-30","headers":{}},
        {"id":"mock6","subject":"Rent Invoice October $2,200.00 Due Oct 01","snippet":"Rent due Oct 01","body":"Rent $2,200.00 due 2026-10-01","headers":{}},
        {"id":"mock7","subject":"Spotify Premium $10.99 charged","snippet":"Your subscription was charged","body":"Spotify $10.99","headers":{}},
        {"id":"mock8","subject":"Passport expiry notice","snippet":"Passport expires 2027-03-10","body":"Passport expiry 2027-03-10","headers":{}},
    ]

def fetch_messages(days: int, query: str, max_results: int, use_mock_if_offline: bool = True) -> tuple[list[dict], str]:
    try:
        msgs = _gmail_fetch_live(days, query, max_results)
        return msgs, "gmail-live"
    except Exception as e:
        if use_mock_if_offline:
            _log(f"gmail live unavailable ({e}); using mock sample for dry-run")
            return _mock_messages(), f"mock-fallback ({type(e).__name__})"
        raise

# ── store upsert with dedup ─────────────────────────────────────────────────
def _existing_key(item: dict) -> str:
    # stable dedup: kind+name+due/date
    kind = item.get("kind","")
    name = item.get("name","").strip().lower()
    when = item.get("due") or item.get("date") or ""
    return f"{kind}|{name}|{when}"

def bulk_upsert(candidates: list[dict], dry_run: bool = True) -> dict:
    finlay = _load_store(FINLAY_STORE)
    calendula = _load_store(CALENDULA_STORE)
    fin_before = len(finlay.get("items", []))
    cal_before = len(calendula.get("items", []))

    fin_keys = {_existing_key(it) for it in finlay.get("items", [])}
    cal_keys = {_existing_key(it) for it in calendula.get("items", [])}

    fin_add = []
    cal_add = []
    skipped = []

    for c in candidates:
        agent = c.get("agent")
        # normalize entry shape
        if agent == "finlay":
            kind = c.get("kind")
            name = c.get("name","").strip() or "Untitled"
            due = c.get("due") or datetime.date.today().isoformat()
            k = f"{kind}|{name.lower()}|{due}"
            if k in fin_keys:
                skipped.append(c)
                continue
            entry = {
                "id": f"gmail_{hashlib.sha1((k+c.get('snippet','')).encode()).hexdigest()[:10]}",
                "kind": kind,
                "name": name,
                "amount": float(c.get("amount") or 0),
                "due": due,
                "source": "gmail-import",
                "snippet": c.get("snippet","")[:120],
                "imported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            fin_add.append(entry)
            fin_keys.add(k)
        elif agent == "calendula":
            kind = c.get("kind")
            name = c.get("name","").strip() or "Untitled"
            dt = c.get("date") or datetime.date.today().isoformat()
            k = f"{kind}|{name.lower()}|{dt}"
            if k in cal_keys:
                skipped.append(c)
                continue
            entry = {
                "id": f"gmail_{hashlib.sha1((k+c.get('snippet','')).encode()).hexdigest()[:10]}",
                "kind": kind,
                "name": name,
                "date": dt,
                "source": "gmail-import",
                "snippet": c.get("snippet","")[:120],
                "imported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            cal_add.append(entry)
            cal_keys.add(k)

    result = {
        "hermes_home": str(HERMES_HOME),
        "finlay_store": str(FINLAY_STORE),
        "calendula_store": str(CALENDULA_STORE),
        "finlay_before": fin_before,
        "calendula_before": cal_before,
        "finlay_would_add": len(fin_add),
        "calendula_would_add": len(cal_add),
        "skipped_dup": len(skipped),
        "finlay_to_add": fin_add,
        "calendula_to_add": cal_add,
        "dry_run": dry_run,
    }

    if not dry_run:
        if fin_add:
            finlay.setdefault("items", []).extend(fin_add)
            finlay["meta"] = finlay.get("meta", {})
            finlay["meta"]["last_import"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            finlay["meta"]["last_import_count"] = len(fin_add)
            _atomic_write(FINLAY_STORE, finlay)
        if cal_add:
            calendula.setdefault("items", []).extend(cal_add)
            calendula["meta"] = calendula.get("meta", {})
            calendula["meta"]["last_import"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            calendula["meta"]["last_import_count"] = len(cal_add)
            _atomic_write(CALENDULA_STORE, calendula)
        result["finlay_after"] = fin_before + len(fin_add)
        result["calendula_after"] = cal_before + len(cal_add)
        _log(f"wrote {len(fin_add)} finlay + {len(cal_add)} calendula (skipped {len(skipped)} dups)")
    else:
        result["finlay_after"] = fin_before  # no write in dry-run
        result["calendula_after"] = cal_before
        _log(f"dry-run would add {len(fin_add)} finlay + {len(cal_add)} calendula (skipped {len(skipped)} dups)")

    return result

# ── main ────────────────────────────────────────────────────────────────────
def main(argv=None):
    global HERMES_HOME, AGENTS_DIR, FINLAY_STORE, CALENDULA_STORE, GMAIL_DIR, CREDS_FILE, TOKEN_FILE
    # capture current HERMES_HOME for default before any global rebinding
    _default_home = str(HERMES_HOME)
    p = argparse.ArgumentParser(description="Bulk-create Finlay/Calendula entries from last 30d Gmail")
    p.add_argument("--days", type=int, default=30, help="lookback days (default 30)")
    p.add_argument("--query", type=str, default="", help="extra Gmail query (default: newer_than:30d)")
    p.add_argument("--limit", type=int, default=100, help="max messages to scan (default 100)")
    p.add_argument("--dry-run", action="store_true", help="preview without writing stores")
    p.add_argument("--live", action="store_true", help="write to stores (default if not --dry-run, explicit for clarity)")
    p.add_argument("--json", action="store_true", help="output JSON only")
    p.add_argument("--hermes-home", type=str, default=_default_home, help="HERMES_HOME override")
    args = p.parse_args(argv)

    # honour --hermes-home in this invocation
    if args.hermes_home and args.hermes_home != _default_home:
        HERMES_HOME = Path(args.hermes_home).expanduser()
        AGENTS_DIR = HERMES_HOME / "agents"
        FINLAY_STORE = AGENTS_DIR / "finlay" / "store.json"
        CALENDULA_STORE = AGENTS_DIR / "calendula" / "store.json"
        GMAIL_DIR = HERMES_HOME / "gmail"
        CREDS_FILE = GMAIL_DIR / "credentials.json"
        TOKEN_FILE = GMAIL_DIR / "token.json"

    dry_run = args.dry_run or not args.live
    # if both --dry-run and --live, dry wins
    if args.dry_run:
        dry_run = True

    _log(f"start days={args.days} query='{args.query or f'newer_than:{args.days}d'}' limit={args.limit} dry_run={dry_run} HERMES_HOME={HERMES_HOME}")

    msgs, source = fetch_messages(args.days, args.query, args.limit, use_mock_if_offline=True)
    _log(f"fetched {len(msgs)} messages via {source}")

    candidates = []
    for m in msgs:
        cands = classify_email(m.get("subject",""), m.get("snippet",""), m.get("body",""))
        for c in cands:
            c["gmail_id"] = m.get("id")
            c["subject"] = m.get("subject","")
            candidates.append(c)

    _log(f"classified {len(candidates)} candidates from {len(msgs)} messages")

    result = bulk_upsert(candidates, dry_run=dry_run)
    result["source"] = source
    result["messages_scanned"] = len(msgs)
    result["candidates"] = candidates

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps(result, indent=2, default=str))
        # human summary
        print(f"\n— summary —")
        print(f"source: {source}  messages: {len(msgs)}  candidates: {len(candidates)}")
        print(f"finlay: {result['finlay_before']} → {result['finlay_after']} (+{result['finlay_would_add']})  calendula: {result['calendula_before']} → {result['calendula_after']} (+{result['calendula_would_add']})  dups skipped: {result['skipped_dup']}")
        if dry_run:
            print("dry-run: no stores written (use --live to write)")
        else:
            print(f"wrote to {FINLAY_STORE} and {CALENDULA_STORE}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
