#!/usr/bin/env python3
"""One-shot Gmail OAuth: generates URL with PKCE, then exchanges code for token.
Since the auth code from Google's redirect must be paired with the same
code_verifier used to generate the URL, this script must run in two phases:

  Phase 1 (generate URL):   python3 auth_gmail.py --url
  Phase 2 (exchange code): python3 auth_gmail.py --code "4/0AXEQx..."

The code_verifier is saved to ~/.hermes/gmail/code_verifier between phases.
"""
import json, os, sys
from pathlib import Path

CREDS_FILE = Path.home() / ".hermes" / "gmail" / "credentials.json"
TOKEN_FILE = Path.home() / ".hermes" / "gmail" / "token.json"
VERIFIER_FILE = Path.home() / ".hermes" / "gmail" / "code_verifier"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]

from google_auth_oauthlib.flow import InstalledAppFlow

def _make_flow():
    return InstalledAppFlow.from_client_secrets_file(
        str(CREDS_FILE), SCOPES, redirect_uri="http://localhost"
    )

if __name__ == "__main__":
    if "--url" in sys.argv:
        # Phase 1: generate auth URL with PKCE code_verifier
        flow = _make_flow()
        auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
        # Save the code_verifier so we can reuse it in Phase 2
        VERIFIER_FILE.parent.mkdir(parents=True, exist_ok=True)
        VERIFIER_FILE.write_text(flow.code_verifier)
        print(f"\n🔗 Open this URL in your browser:\n{auth_url}\n")
        print("After granting consent, copy the 'code' parameter from the")
        print("redirect URL (it looks like: 4/0AXEQx...) and run:")
        print(f"  python3 {sys.argv[0]} --code PASTE_CODE_HERE")
    elif "--code" in sys.argv:
        # Phase 2: exchange code for token (must use same code_verifier)
        code = sys.argv[sys.argv.index("--code") + 1]
        if not VERIFIER_FILE.exists():
            print("ERROR: No code_verifier found. Run without --code first to get the URL.")
            sys.exit(1)
        verifier = VERIFIER_FILE.read_text().strip()
        VERIFIER_FILE.unlink(missing_ok=True)

        flow = _make_flow()
        flow.code_verifier = verifier
        flow.fetch_token(code=code)
        creds = flow.credentials
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())
        print(f"\n✅ Token saved to {TOKEN_FILE}")
        scopes_json = json.loads(creds.to_json())
        print("Scopes:", scopes_json.get("scopes", []))
    else:
        # Default: generate URL (same as --url)
        flow = _make_flow()
        auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
        VERIFIER_FILE.parent.mkdir(parents=True, exist_ok=True)
        VERIFIER_FILE.write_text(flow.code_verifier)
        print(f"\n🔗 Open this URL in your browser:\n{auth_url}\n")
        print("Paste the authorization code here:", end=" ", flush=True)
        code = sys.stdin.readline().strip()
        if not code:
            print("No code received. Aborting.")
            sys.exit(1)
        verifier = VERIFIER_FILE.read_text().strip()
        VERIFIER_FILE.unlink(missing_ok=True)
        flow2 = _make_flow()
        flow2.code_verifier = verifier
        flow2.fetch_token(code=code)
        creds = flow2.credentials
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())
        print(f"\n✅ Token saved to {TOKEN_FILE}")
        scopes_json = json.loads(creds.to_json())
        print("Scopes:", scopes_json.get("scopes", []))
