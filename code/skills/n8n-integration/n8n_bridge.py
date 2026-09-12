#!/usr/bin/env python3
"""Bridge between Hermes and n8n webhooks.

Called by Hermes when a /n8n command is received.
Triggers an n8n webhook workflow and returns the result.
"""

import json
import os
import sys
import urllib.request
import urllib.error

N8N_BASE = os.environ.get("N8N_BASE_URL", "http://localhost:5678")
N8N_USER = os.environ.get("N8N_BASIC_AUTH_USER", "admin")
N8N_PASS = os.environ.get("N8N_BASIC_AUTH_PASSWORD", "")

WORKFLOWS = {
    "ping": "webhook/ping",
    "echo": "webhook/echo",
    "telegram-forward": "webhook/telegram-forward",
}


def trigger_webhook(workflow_name: str, payload: dict = None) -> dict:
    webhook_path = WORKFLOWS.get(workflow_name)
    if not webhook_path:
        return {"error": f"Unknown workflow: {workflow_name}. Available: {list(WORKFLOWS.keys())}"}
    
    url = f"{N8N_BASE}/{webhook_path}"
    
    # Basic auth
    import base64
    auth = base64.b64encode(f"{N8N_USER}:{N8N_PASS}".encode()).decode()
    
    data = json.dumps(payload or {}).encode() if payload else None
    
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth}"
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            return {"status": resp.status, "body": json.loads(body) if body else {}}
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def main():
    if len(sys.argv) < 2:
        print("Usage: /n8n <workflow_name> [json_payload]")
        print(f"Available workflows: {list(WORKFLOWS.keys())}")
        sys.exit(1)
    
    workflow = sys.argv[1]
    payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    
    result = trigger_webhook(workflow, payload)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
