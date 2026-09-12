#!/usr/bin/env python3
"""alerts_delivery.py — Deliver undelivered alerts from inbox to Telegram."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

ALERTS_FILE = Path.home() / ".hermes" / "data" / "alerts_inbox.jsonl"
MAX_BURST = 3


def send_message(text: str) -> bool:
    # Wrap alert with personality
    try:
        import subprocess, sys as _sys
        from pathlib import Path as _P
        r = subprocess.run(
            [_sys.executable, str(_P.home() / ".hermes" / "scripts" / "persona_engine.py"), "alert", text[:200], "--dry-run"],
            capture_output=True, text=True, timeout=10
        )
        if r.stdout.strip():
            text = r.stdout.strip()
    except Exception:
        pass
    try:
        from telegram_bridge import send_telegram
        return send_telegram(text[:4096]).get("status") == "ok"
    except Exception:
        return False


def _dedup(alerts):
    """Remove duplicate alert messages by source+msg hash."""
    seen = set()
    unique = []
    for a in reversed(alerts):
        key = (a.get("source",""), a.get("message","")[:100])
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return list(reversed(unique))

def deliver():
    import hashlib
    lockfile = Path("/tmp/alerts_delivery.lock")
    if lockfile.exists() and time.time() - lockfile.stat().st_mtime < 60:
        print("Skipping: another delivery running")
        return
    lockfile.touch()

    if not ALERTS_FILE.exists():
        print("No alert file")
        lockfile.unlink(missing_ok=True)
        return
    try:
        raw = ALERTS_FILE.read_text().strip()
        if not raw:
            lockfile.unlink(missing_ok=True)
            return
        alerts = json.loads(raw) if raw.startswith("[") else []
    except (json.JSONDecodeError, OSError) as e:
        print(f"Read error: {e}")
        lockfile.unlink(missing_ok=True)
        return

    alerts = _dedup(alerts)
    undelivered = [a for a in alerts if not a.get("delivered", False)]
    if not undelivered:
        print("All delivered")
        return

    sent = 0
    for alert in undelivered[:MAX_BURST]:
        msg = alert.get("message", "")
        source = alert.get("source", "unknown")

        full = f"[{source}] {msg}"
        ok = send_message(full)
        if ok:
            alert["delivered"] = True
            alert["delivered_at"] = datetime.now(timezone.utc).isoformat()
            sent += 1
            print(f"  Sent: {source}")

    changed = False
    if sent:
        changed = True
        print(f"Delivered {sent}")

    # Prune old delivered entries (keep last 20)
    delivered = [a for a in alerts if a.get("delivered", False)]
    if len(delivered) > 20:
        undelivered_alerts = [a for a in alerts if not a.get("delivered", False)]
        alerts = undelivered_alerts + delivered[-20:]
        changed = True
        print(f"Pruned to {len(alerts)} entries")

    if changed:
        ALERTS_FILE.write_text(json.dumps(alerts, indent=2))
    elif not sent:
        print(f"Failed to send any of {len(undelivered)} undelivered")

if __name__ == "__main__":
    try:
        deliver()
    except Exception as e:
        print(f"Delivery error: {e}")
        lockfile = Path("/tmp/alerts_delivery.lock")
        lockfile.unlink(missing_ok=True)
