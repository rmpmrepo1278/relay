#!/usr/bin/env python3
"""OAuth credential setup for Hermes MCP servers.

Sets up Google OAuth credentials with Gmail + Calendar scopes.

Usage:
    python3 setup.py                  # local desktop (default, opens browser)
    python3 setup.py --force          # re-authenticate
    python3 setup.py --console        # URL-based auth (for SSH)
    python3 setup.py --port 8888      # use specific port (for SSH -L forwarding)

For SSH: either use --console (paste auth code) or --port + ssh -L:
    ssh -L 8888:localhost:8888 <host>
    python3 setup.py --port 8888
"""

import os
import sys
import json
import argparse
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
CREDENTIALS_DIR = HERMES_HOME / "gmail"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"
TOKEN_FILE = CREDENTIALS_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


def setup_credentials(force: bool = False, console: bool = False, port: int = 0):
    creds = None

    if TOKEN_FILE.exists() and not force:
        print(f"Existing token found at {TOKEN_FILE}")
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        existing_scopes = set(creds.scopes or [])
        missing = set(SCOPES) - existing_scopes
        if missing:
            print(f"Missing scopes: {', '.join(missing)}")
            print("Re-authenticating...")
            creds = None
        else:
            print("All scopes present and token valid!")
            return

    if creds and creds.expired and creds.refresh_token:
        print("Refreshing expired token...")
        creds.refresh(Request())
        if creds.valid:
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
            print("Token refreshed!")
            return

    if not CREDENTIALS_FILE.exists():
        print(
            f"ERROR: No credentials.json found at {CREDENTIALS_FILE}\n\n"
            "To create one:\n"
            "1. Go to https://console.cloud.google.com/apis/credentials\n"
            "2. Create OAuth 2.0 Client ID (Desktop App type)\n"
            "3. Download the JSON and save it to:\n"
            f"   {CREDENTIALS_FILE}\n"
        )
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_FILE), SCOPES
    )

    if console:
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        auth_url, _ = flow.authorization_url(prompt="consent")
        print("\nOpen this URL in your browser:")
        print(auth_url)
        print("\nAuthorize the app, then paste the full redirect URL or code below.")
        result = input("Authorization response (URL or code): ").strip()
        if "code=" in result:
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(result).query)
            code = qs.get("code", [result])[0]
        else:
            code = result
        flow.fetch_token(code=code)
        creds = flow.credentials
    else:
        kwargs = {}
        if port:
            kwargs["port"] = port
            kwargs["open_browser"] = False
            print(f"Starting local server on port {port}...")
            print("Open the URL below in a browser on this machine:")
        creds = flow.run_local_server(**kwargs)

    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    print(f"\nToken saved to {TOKEN_FILE}")
    print("Scopes granted:", json.dumps(SCOPES, indent=2))
    print("\nAll set! MCP credentials ready.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Set up MCP OAuth credentials")
    parser.add_argument("--force", action="store_true", help="Force re-auth")
    parser.add_argument("--console", action="store_true", help="URL-based auth for SSH")
    parser.add_argument("--port", type=int, default=0, help="Port for local server")
    args = parser.parse_args()
    setup_credentials(force=args.force, console=args.console, port=args.port)
