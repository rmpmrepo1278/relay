#!/usr/bin/env python3
"""task_executor.py — Executes pending tasks from the BabyAGI task queue.

Runs every 15 minutes. Picks highest-priority pending task and executes it.
Two execution tiers:
  - research: run research_consumer or mark as reviewed
  - general: escalate to alert (can't auto-execute)

Infra tasks (docker restart, health check) are delegated to n8n workflows.
"""

import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
QUEUE_FILE = HERMES_HOME / "state" / "task_queue.json"
ALERTS_INBOX = Path.home() / ".hermes" / "data" / "alerts_inbox.jsonl"
STATE_FILE = HERMES_HOME / "data" / "task_executor_state.json"


def load_queue():
    if QUEUE_FILE.exists():
        return json.loads(QUEUE_FILE.read_text())
    return {"tasks": [], "completed": [], "last_updated": None}


def save_queue(queue):
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    queue["last_updated"] = datetime.now().isoformat()
    QUEUE_FILE.write_text(json.dumps(queue, indent=2, default=str))


def push_alert(message, severity="info"):
    entry = {
        "severity": severity, "message": message,
        "source": "task_executor",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "delivered": False, "requires_approval": False, "actions": [],
    }
    try:
        ALERTS_INBOX.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if ALERTS_INBOX.exists():
            content = ALERTS_INBOX.read_text().strip()
            if content:
                existing = json.loads(content) if content.startswith("[") else []
        existing.append(entry)
        ALERTS_INBOX.write_text(json.dumps(existing, indent=2))
    except OSError:
        pass


def execute_research_task(task):
    title = task.get("title", "")
    context = task.get("context", "")

    url = ""
    if "URL:" in context:
        url = context.split("URL:")[-1].strip().split()[0]

    if url:
        result = subprocess.run(
            [sys.executable, str(HERMES_HOME / "scripts/research_consumer.py"), url],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            return {"status": "resolved", "detail": f"Consumed {url}"}
        return {"status": "partial", "detail": f"Could not consume {url}"}

    return {"status": "deferred", "detail": "No URL to process"}


def execute_task(task):
    domain = task.get("domain", "general")
    title = task.get("title", "")

    if domain in ("research", "research_consumer"):
        return execute_research_task(task)
    elif domain == "manual":
        return {"status": "deferred", "detail": "Manual task requires human review"}
    elif domain in ("infra", "infrastructure"):
        return {"status": "deferred", "detail": "Infra tasks handled by n8n workflows"}
    else:
        return {"status": "escalated", "detail": f"Unknown domain: {domain}"}


def run():
    state = {"last_run": None, "tasks_executed": 0, "tasks_deferred": 0}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    queue = load_queue()
    tasks = queue.get("tasks", [])
    pending = [t for t in tasks if t.get("status") == "pending"]

    if not pending:
        print("No pending tasks")
        state["last_run"] = datetime.now().isoformat()
        STATE_FILE.write_text(json.dumps(state, indent=2))
        return

    pending.sort(key=lambda t: (-t.get("priority", 5), t.get("created", "")))
    task = pending[0]
    print(f"Executing [{task['id']}] {task['title']} (priority {task['priority']}, domain {task['domain']})")

    result = execute_task(task)

    for t in tasks:
        if t["id"] == task["id"]:
            t["status"] = "completed" if result["status"] in ("resolved", "deferred") else result["status"]
            t["result"] = result["detail"]
            t["executed_at"] = datetime.now().isoformat()
            break

    queue["tasks"] = tasks
    save_queue(queue)

    msg = f"Task [{task['id'][:8]}] {task['title'][:80]}"
    msg += f"\n  Result: {result['status']} -- {result['detail'][:200]}"
    push_alert(msg, severity="info" if result["status"] == "resolved" else "warning")

    state["last_run"] = datetime.now().isoformat()
    state["tasks_executed"] += 1
    if result["status"] in ("deferred", "escalated"):
        state["tasks_deferred"] += 1
    STATE_FILE.write_text(json.dumps(state, indent=2))

    print(f"  Status: {result['status']}")
    print(f"  Detail: {result['detail'][:200]}")


if __name__ == "__main__":
    run()
