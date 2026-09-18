#!/usr/bin/env python3
"""agentscape_digest.py - nightly Autonomous Agent Digest to the personal topic.

Wraps agentscape.send_digest with the personal-topic thread id so systemd runs
the exact same entrypoint as `python3 -m agentscape` but pinned to 10122.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".hermes" / "agents"))

try:
    import agentscape
except Exception as e:  # noqa: BLE001
    print("agentscape unavailable:", e)
    sys.exit(1)

HOURS = int(os.environ.get("DIGEST_HOURS", "24"))
PERSONAL_TOPIC = int(os.environ.get("DIGEST_TOPIC", "10122"))

if __name__ == "__main__":
    out = agentscape.send_digest(thread=PERSONAL_TOPIC, hours=HOURS)
    ok = str(out.get("status") or out.get("ok")).lower() in ("ok", "true", "success", "sent")
    print("digest:", json := __import__("json").dumps(out)[:300])
    sys.exit(0 if ok else 1)