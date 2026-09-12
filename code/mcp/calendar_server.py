#!/usr/bin/env python3
"""Google Calendar MCP Server — read/create/update calendar events via Hermes.

Protocol: MCP stdio transport (JSON-RPC over stdin/stdout).
Uses Google OAuth credentials from ~/.hermes/gmail/ (with calendar scopes).
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("calendar-mcp")

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
CREDENTIALS_DIR = HERMES_HOME / "gmail"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"
TOKEN_FILE = CREDENTIALS_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

server = Server("calendar-mcp")


def get_service():
    """Get authenticated Google Calendar API service."""
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
    return build("calendar", "v3", credentials=creds)


@server.list_tools()
async def handle_list_tools():
    return [
        Tool(
            name="calendar_list_events",
            description="List upcoming calendar events",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Max events (default 10)",
                        "default": 10,
                    },
                    "days_ahead": {
                        "type": "integer",
                        "description": "How many days ahead to look (default 7)",
                        "default": 7,
                    },
                },
            },
        ),
        Tool(
            name="calendar_get_event",
            description="Get details of a specific calendar event by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "Calendar event ID",
                    },
                },
                "required": ["event_id"],
            },
        ),
        Tool(
            name="calendar_create_event",
            description="Create a new calendar event",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Event title",
                    },
                    "description": {
                        "type": "string",
                        "description": "Event description",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Start time in ISO format (e.g. 2026-07-05T14:00:00)",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "End time in ISO format",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "Timezone (default America/Los_Angeles)",
                        "default": "America/Los_Angeles",
                    },
                },
                "required": ["summary", "start_time", "end_time"],
            },
        ),
        Tool(
            name="calendar_find_free_slots",
            description="Find free time slots in the calendar",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date to check (YYYY-MM-DD)",
                    },
                    "min_duration_minutes": {
                        "type": "integer",
                        "description": "Minimum slot duration in minutes (default 30)",
                        "default": 30,
                    },
                },
                "required": ["date"],
            },
        ),
        Tool(
            name="calendar_today_summary",
            description="Get a summary of today's events",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list:
    service = get_service()

    if name == "calendar_list_events":
        max_results = min(arguments.get("max_results", 10), 50)
        days_ahead = arguments.get("days_ahead", 7)
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days_ahead)
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=end.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])
        output = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            end = event["end"].get("dateTime", event["end"].get("date"))
            output.append(
                {
                    "id": event["id"],
                    "summary": event.get("summary", "(no title)"),
                    "start": start,
                    "end": end,
                    "location": event.get("location", ""),
                }
            )
        return [TextContent(type="text", text=json.dumps(output, indent=2))]

    elif name == "calendar_get_event":
        event = (
            service.events()
            .get(calendarId="primary", eventId=arguments["event_id"])
            .execute()
        )
        return [TextContent(type="text", text=json.dumps(event, indent=2, default=str))]

    elif name == "calendar_create_event":
        timezone_str = arguments.get("timezone", "America/Los_Angeles")
        event_body = {
            "summary": arguments["summary"],
            "description": arguments.get("description", ""),
            "start": {
                "dateTime": arguments["start_time"],
                "timeZone": timezone_str,
            },
            "end": {
                "dateTime": arguments["end_time"],
                "timeZone": timezone_str,
            },
        }
        created = (
            service.events()
            .insert(calendarId="primary", body=event_body)
            .execute()
        )
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "created": True,
                        "id": created["id"],
                        "summary": created.get("summary"),
                        "htmlLink": created.get("htmlLink"),
                    },
                    indent=2,
                ),
            )
        ]

    elif name == "calendar_find_free_slots":
        date_str = arguments["date"]
        min_duration = timedelta(minutes=arguments.get("min_duration_minutes", 30))
        day_start = datetime.fromisoformat(f"{date_str}T00:00:00").replace(
            tzinfo=timezone.utc
        )
        day_end = datetime.fromisoformat(f"{date_str}T23:59:59").replace(
            tzinfo=timezone.utc
        )
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])
        busy_slots = []
        for event in events:
            start_str = event["start"].get(
                "dateTime", event["start"].get("date")
            )
            end_str = event["end"].get("dateTime", event["end"].get("date"))
            try:
                s = datetime.fromisoformat(start_str)
                e = datetime.fromisoformat(end_str)
                busy_slots.append((s, e))
            except ValueError:
                pass
        busy_slots.sort()
        free_slots = []
        cursor = day_start
        for start, end in busy_slots:
            if cursor < start and (start - cursor) >= min_duration:
                free_slots.append(
                    {
                        "start": cursor.isoformat(),
                        "end": start.isoformat(),
                        "duration_minutes": int((start - cursor).total_seconds() / 60),
                    }
                )
            cursor = max(cursor, end)
        if cursor < day_end and (day_end - cursor) >= min_duration:
            free_slots.append(
                {
                    "start": cursor.isoformat(),
                    "end": day_end.isoformat(),
                    "duration_minutes": int((day_end - cursor).total_seconds() / 60),
                }
            )
        return [TextContent(type="text", text=json.dumps(free_slots, indent=2))]

    elif name == "calendar_today_summary":
        now = datetime.now(timezone.utc)
        day_end = now.replace(hour=23, minute=59, second=59)
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])
        output = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            end = event["end"].get("dateTime", event["end"].get("date"))
            output.append(
                {
                    "summary": event.get("summary", "(no title)"),
                    "start": start,
                    "end": end,
                    "location": event.get("location", ""),
                }
            )
        summary = {
            "date": now.strftime("%Y-%m-%d"),
            "event_count": len(output),
            "events": output,
        }
        return [TextContent(type="text", text=json.dumps(summary, indent=2))]

    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
