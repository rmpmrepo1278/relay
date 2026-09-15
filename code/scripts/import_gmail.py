#!/usr/bin/env python3
"""import_gmail.py — Bulk import Gmail last 30d into Finlay/Calendula/Connector stores."""
import json, os, sys, datetime, pathlib, re
HERMES_HOME=pathlib.Path.home() / ".hermes"
sys.path.insert(0, str(HERMES_HOME / "scripts"))
try:
    from email_intelligence import get_gmail_service
    from googleapiclient.errors import HttpError
except Exception as e:
    print(f"import failed: {e}")
    sys.exit(1)

def fetch_gmail_last_30d():
    service=get_gmail_service()
    # Use Gmail API to list messages from last 30d
    q="newer_than:30d"
    results=service.users().messages().list(userId="me", q=q, maxResults=100).execute()
    messages=results.get("messages",[])
    print(f"Found {len(messages)} messages in last 30d")
    out=[]
    for msg in messages[:20]:
        m=service.users().messages().get(userId="me", id=msg["id"], format="metadata", metadataHeaders=["From","Subject","Date"]).execute()
        headers={h["name"]:h["value"] for h in m.get("payload",{}).get("headers",[])}
        snippet=m.get("snippet","")[:200]
        out.append({"id":msg["id"], "from":headers.get("From",""), "subject":headers.get("Subject",""), "date":headers.get("Date",""), "snippet":snippet})
    return out

def classify_and_import():
    msgs=fetch_gmail_last_30d()
    finlay_added=0
    calendula_added=0
    connector_added=0
    for m in msgs:
        subj=m["subject"].lower()
        snippet=m["snippet"].lower()
        text=subj+" "+snippet
        # Simple classification
        if any(k in text for k in ["bill","invoice","payment due","charged","subscription","receipt"]):
            # Finlay: try to extract amount and due date
            print(f"Finlay candidate: {m['subject'][:60]}")
            finlay_added+=1
        if any(k in text for k in ["appointment","meeting","calendar","invite","expir","passport","prescription"]):
            print(f"Calendula candidate: {m['subject'][:60]}")
            calendula_added+=1
        if any(k in text for k in ["birthday","anniversary","follow up","reconnect"]):
            print(f"Connector candidate: {m['subject'][:60]}")
            connector_added+=1
    print(f"Import dry-run: Finlay {finlay_added}, Calendula {calendula_added}, Connector {connector_added}")
    # For now, dry-run only – actual import would call finlay.py etc.
    return {"finlay":finlay_added, "calendula":calendula_added, "connector":connector_added}

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Dry run only")
    args=p.parse_args()
    res=classify_and_import()
    print(f"Done: {res}")

