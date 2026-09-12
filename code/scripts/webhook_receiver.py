#!/usr/bin/env python3
"""Simple webhook receiver for Hermes outbound events."""
import json, sys
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

LOG_DIR = Path.home() / ".hermes" / "logs"
LOG_FILE = LOG_DIR / "webhooks.log"

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {"raw": body.decode(errors="replace")}
        event = data.get("hook_event_name", "unknown")
        ts = data.get("timestamp", datetime.now(timezone.utc).isoformat())
        session = data.get("session_id", "?")
        tool = data.get("tool_name", "-")
        line = f"[{ts}] event={event} session={session} tool={tool}\n"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line)
            extra = data.get("extra")
            if extra:
                f.write(f"  extra: {json.dumps(extra, default=str)[:500]}\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "healthy"}).encode())

    def log_message(self, fmt, *args):
        pass

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9200
    server = HTTPServer(("127.0.0.1", port), WebhookHandler)
    print(f"Webhook receiver on 127.0.0.1:{port}", flush=True)
    server.serve_forever()
