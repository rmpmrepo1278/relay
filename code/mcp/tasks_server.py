#!/usr/bin/env python3
"""Local Tasks MCP Server — task management stored in ~/.hermes/tasks.json.

Protocol: MCP stdio transport (JSON-RPC over stdin/stdout).
No external API needed — tasks stored locally.
"""

import os
import json
import asyncio
import logging
from datetime import datetime, date
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("tasks-mcp")

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
TASKS_FILE = HERMES_HOME / "tasks.json"

server = Server("tasks-mcp")


def load_tasks():
    if TASKS_FILE.exists():
        return json.loads(TASKS_FILE.read_text())
    return []


def save_tasks(tasks):
    TASKS_FILE.write_text(json.dumps(tasks, indent=2, default=str))


@server.list_tools()
async def handle_list_tools():
    return [
        Tool(
            name="tasks_list",
            description="List all tasks, optionally filtered by status or priority",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by status: pending, in_progress, done, cancelled",
                    },
                    "priority": {
                        "type": "string",
                        "description": "Filter by priority: high, medium, low",
                    },
                },
            },
        ),
        Tool(
            name="tasks_add",
            description="Add a new task",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Task title"},
                    "description": {
                        "type": "string",
                        "description": "Task description",
                    },
                    "priority": {
                        "type": "string",
                        "description": "Priority: high, medium, low (default medium)",
                        "default": "medium",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "Due date (YYYY-MM-DD)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for categorization",
                    },
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="tasks_update",
            description="Update a task's status, priority, or details",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "Task ID (from tasks_list)",
                    },
                    "status": {
                        "type": "string",
                        "description": "New status: pending, in_progress, done, cancelled",
                    },
                    "priority": {
                        "type": "string",
                        "description": "New priority: high, medium, low",
                    },
                    "title": {"type": "string", "description": "New title"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="tasks_delete",
            description="Delete a task by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "Task ID to delete",
                    },
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="tasks_summary",
            description="Get a summary of tasks (counts by status/priority, overdue)",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list:
    tasks = load_tasks()

    if name == "tasks_list":
        result = tasks
        if "status" in arguments:
            result = [t for t in result if t.get("status") == arguments["status"]]
        if "priority" in arguments:
            result = [t for t in result if t.get("priority") == arguments["priority"]]
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    elif name == "tasks_add":
        new_id = max([t.get("id", 0) for t in tasks], default=0) + 1
        task = {
            "id": new_id,
            "title": arguments["title"],
            "description": arguments.get("description", ""),
            "priority": arguments.get("priority", "medium"),
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "due_date": arguments.get("due_date", ""),
            "tags": arguments.get("tags", []),
        }
        tasks.append(task)
        save_tasks(tasks)
        return [TextContent(type="text", text=json.dumps({"created": True, "id": new_id, "task": task}, indent=2, default=str))]

    elif name == "tasks_update":
        task_id = arguments["task_id"]
        for task in tasks:
            if task["id"] == task_id:
                for key in ("status", "priority", "title"):
                    if key in arguments:
                        task[key] = arguments[key]
                task["updated_at"] = datetime.now().isoformat()
                save_tasks(tasks)
                return [TextContent(type="text", text=json.dumps({"updated": True, "task": task}, indent=2, default=str))]
        return [TextContent(type="text", text=json.dumps({"error": f"Task {task_id} not found"}))]

    elif name == "tasks_delete":
        task_id = arguments["task_id"]
        before = len(tasks)
        tasks = [t for t in tasks if t["id"] != task_id]
        if len(tasks) < before:
            save_tasks(tasks)
            return [TextContent(type="text", text=json.dumps({"deleted": True, "id": task_id}))]
        return [TextContent(type="text", text=json.dumps({"error": f"Task {task_id} not found"}))]

    elif name == "tasks_summary":
        total = len(tasks)
        by_status = {}
        by_priority = {}
        overdue = []
        today = date.today()
        for t in tasks:
            s = t.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
            p = t.get("priority", "none")
            by_priority[p] = by_priority.get(p, 0) + 1
            if t.get("due_date") and t.get("status") in ("pending", "in_progress"):
                try:
                    due = datetime.fromisoformat(t["due_date"]).date()
                    if due < today:
                        overdue.append({"id": t["id"], "title": t["title"], "due": t["due_date"]})
                except (ValueError, TypeError):
                    pass
        return [TextContent(type="text", text=json.dumps({
            "total": total,
            "by_status": by_status,
            "by_priority": by_priority,
            "overdue_count": len(overdue),
            "overdue_tasks": overdue,
        }, indent=2, default=str))]

    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
