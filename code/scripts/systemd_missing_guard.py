#!/usr/bin/env python3
"""systemd_missing_guard.py — ExecStartPre guard.

Detects when a service's ExecStart points at a missing file and alerts via
Telegram, so a missing dependency surfaces instead of silent restart loops.

Usage (in a unit):
  ExecStartPre=/home/rohit/.hermes/scripts/systemd_missing_guard.py /path/to/main/script [extra]
  If the main script is missing, this exits 1 (which with a oneshot + Restart
  would loop) — better to pair with GuardDetects absence.
"""
import os, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

def alert(msg: str) -> None:
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from telegram_bridge import send_telegram
        send_telegram("⚠️ " + msg)
    except Exception as e:
        print("alert failed:", e)

def main() -> int:
    if len(sys.argv) < 2:
        print("usage: missing_guard.py <exec_path> [args...]")
        return 2
    exec_path = sys.argv[1]
    p = Path(os.path.expanduser(exec_path))
    if p.exists():
        return 0  # exists, allow the service to run
    host = os.uname().nodename
    alert(f"[{host}] Service blocked: ExecStart file missing `{exec_path}`. "
          f"Exiting before start.")
    print(f"BLOCKED on missing ExecStart file: {exec_path}")
    return 3  # non-zero -> stop the oneshot before ExecStart

if __name__ == "__main__":
    sys.exit(main())
