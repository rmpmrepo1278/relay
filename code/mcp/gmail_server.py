#!/usr/bin/env python3
"""Gmail MCP Server — read/search/send emails via Hermes conversations.

Protocol: MCP stdio transport (JSON-RPC over stdin/stdout).
Uses Google OAuth credentials from ~/.hermes/gmail/credentials.json.
"""

import os
import json
import base64
import asyncio
import logging
from pathlib import Path
from email.mime.text import MIMEText

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, LoggingLevel

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("gmail-mcp")

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
CREDENTIALS_DIR = HERMES_HOME / "gmail"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"
TOKEN_FILE = CREDENTIALS_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

server = Server("gmail-mcp")


def get_service():
    """Get authenticated Gmail API service."""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise RuntimeError(
                    f"No credentials.json found at {CREDENTIALS_FILE}. "
                    "Run the OAuth setup script first."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


@server.list_tools()
async def handle_list_tools():
    return [
        Tool(
            name="gmail_list_messages",
            description="List messages in Gmail inbox with optional query filter",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query (e.g. 'from:someone is:unread')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max messages to return (default 10)",
                        "default": 10,
                    },
                },
            },
        ),
        Tool(
            name="gmail_get_message",
            description="Get full content of a specific Gmail message by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "Gmail message ID",
                    },
                },
                "required": ["message_id"],
            },
        ),
        Tool(
            name="gmail_search",
            description="Search Gmail with a query string",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results (default 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="gmail_send",
            description="Send an email via Gmail",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body text"},
                },
                "required": ["to", "subject", "body"],
            },
        ),
        Tool(
            name="gmail_get_unread_count",
            description="Get count of unread messages in inbox",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list:
    service = get_service()

    if name == "gmail_list_messages":
        query = arguments.get("query", "")
        max_results = min(arguments.get("max_results", 10), 50)
        results = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = results.get("messages", [])
        output = []
        for msg in messages[:max_results]:
            msg_data = (
                service.users()
                .messages()
                .get(userId="me", id=msg["id"], format="metadata")
                .execute()
            )
            headers = {
                h["name"]: h["value"]
                for h in msg_data.get("payload", {}).get("headers", [])
            }
            output.append(
                {
                    "id": msg["id"],
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "snippet": msg_data.get("snippet", ""),
                }
            )
        return [TextContent(type="text", text=json.dumps(output, indent=2))]

    elif name == "gmail_get_message":
        msg_id = arguments["message_id"]
        msg_data = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )
        headers = {
            h["name"]: h["value"]
            for h in msg_data.get("payload", {}).get("headers", [])
        }
        payload = msg_data.get("payload", {})
        body = ""
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain" and part.get("body", {}).get(
                    "data"
                ):
                    body += base64.urlsafe_b64decode(
                        part["body"]["data"]
                    ).decode("utf-8", errors="replace")
        elif payload.get("body", {}).get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode(
                "utf-8", errors="replace"
            )
        result = {
            "id": msg_id,
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "body": body[:10000],
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "gmail_search":
        query = arguments.get("query", "")
        max_results = min(arguments.get("max_results", 5), 20)
        results = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = results.get("messages", [])
        output = []
        for msg in messages[:max_results]:
            msg_data = (
                service.users()
                .messages()
                .get(userId="me", id=msg["id"], format="metadata")
                .execute()
            )
            headers = {
                h["name"]: h["value"]
                for h in msg_data.get("payload", {}).get("headers", [])
            }
            output.append(
                {
                    "id": msg["id"],
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "snippet": msg_data.get("snippet", ""),
                }
            )
        return [TextContent(type="text", text=json.dumps(output, indent=2))]

    elif name == "gmail_send":
        to = arguments["to"]
        subject = arguments["subject"]
        body = arguments["body"]
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"sent": True, "id": sent["id"], "to": to, "subject": subject},
                    indent=2,
                ),
            )
        ]

    elif name == "gmail_get_unread_count":
        profile = service.users().getProfile(userId="me").execute()
        unread = profile.get("messagesTotal", 0)
        return [
            TextContent(
                type="text",
                text=json.dumps({"unread_count": unread}),
            )
        ]

    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
