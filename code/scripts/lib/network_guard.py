#!/usr/bin/env python3
"""network_guard.py — shared outage-window / DNS guard for network-dependent jobs.

Mirrors the internet-outage awareness in mcp_health_watchdog (known outage
window 11PM-9AM PT). Network-dependent jobs (memory_sync, duckdns_update,
dns_healthcheck) call this so they skip silently during the known window
instead of spamming the scheduler with failures they cannot fix.
"""
from __future__ import annotations

import socket
from datetime import datetime


def in_outage_window() -> bool:
    """Known internet outage window: 11PM-9AM PT (heuristic, mirrors watchdog)."""
    try:
        try:
            from zoneinfo import ZoneInfo
            pt_now = datetime.now(ZoneInfo("America/Los_Angeles"))
        except Exception:
            pt_now = datetime.now()
        return pt_now.hour >= 23 or pt_now.hour < 9
    except Exception:
        return False


def dns_resolves(host: str = "github.com", timeout: float = 3) -> bool:
    """True if host resolves via the system resolver."""
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        return True
    except Exception:
        return False


def guard(host: str = "github.com") -> tuple[bool, str]:
    """Return (skip, reason). Skip=True in known outage OR when DNS is down."""
    if in_outage_window():
        return True, "known outage window (11PM-9AM PT, network unreliable)"
    if not dns_resolves(host):
        return True, f"DNS cannot resolve {host} (transient)"
    return False, ""


if __name__ == "__main__":
    import sys
    skip, reason = guard()
    # shell protocol: 0 = skip this cycle, 1 = network ok, proceed
    if skip:
        sys.stdout.write(f"skip: {reason}\n")
        raise SystemExit(0)
    sys.stdout.write("ok\n")
    raise SystemExit(1)