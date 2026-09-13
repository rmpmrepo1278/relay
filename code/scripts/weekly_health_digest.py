#!/usr/bin/env python3
"""weekly_health_digest.py — WS3+WS4: weekly re-audit + Telegram health digest.

Runs every Sunday 08:00 (after cve_scan at 04:30). Gathers live signals,
writes a report file, and sends a compact Telegram summary. Never crashes the
scheduler: every subsystem is wrapped; failures degrade to a note.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HH = Path.home() / ".hermes"
LOG_DIR = HH / "logs"
REPORT_DIR = LOG_DIR
LOCK = HH / "state" / "weekly_health.lock"
CIRCUITS_PY = HH / "scripts" / "circuit_breaker.py"


def run(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def section(title: str) -> str:
    return f"\n## {title}\n"


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    now = datetime.now(timezone.utc)
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── circuits ──
    circ_out = run(f"python3 {CIRCUITS_PY} status", timeout=20)
    lines.append(section("Circuit breakers"))
    lines.append(f"`{circ_out}`" if circ_out else "_(circuit status unavailable)_")

    # ── scheduler failed jobs ──
    lines.append(section("Scheduler job health"))
    try:
        st = json.loads((HH / "data" / "scheduler_state.json").read_text())
        failed = [(n, s.get("last_status"), str(s.get("last_run", ""))[:16])
                  for n, s in st.items()
                  if isinstance(s, dict) and s.get("last_status") in ("failed", "timeout", "error")]
        if failed:
            for n, st_, t in sorted(failed)[:12]:
                lines.append(f"- ❌ {n} ({st_}) @ {t}")
        else:
            lines.append("- ✅ no failed jobs")
    except Exception as e:
        lines.append(f"- ⚠ scheduler state unreadable: {e}")

    # ── disk / RAM ──
    disk = run("df -h / | awk 'NR==2{print $5\" used (\"$3\"/\"$2\") \"}'")
    mem = run("free -h | awk '/Mem:/{print $3\"/\"$2\" used (\"$7\" avail)\"}'")
    lines.append(section("Resources"))
    lines.append(f"- Disk: {disk}")
    lines.append(f"- RAM: {mem}")

    # ── healthchecks ──
    hc = run("sudo -n sqlite3 /home/rohit/services/data/healthchecks/hc.sqlite "
             "\"select name, status, n_pings from api_check order by name;\"", timeout=20)
    lines.append(section("Healthchecks"))
    if hc:
        for row in hc.splitlines():
            parts = row.split("|")
            if len(parts) == 3:
                lines.append(f"- {parts[0]}: {parts[1]} ({parts[2]} pings)")
    else:
        lines.append("- _(no healthchecks data)_")

    # ── CVE scan (first run: Sun 04:30; may not exist yet) ──
    lines.append(section("CVE scan"))
    cve_log = LOG_DIR / "cve_scan.log"
    if cve_log.exists():
        txt = cve_log.read_text(errors="replace")
        crit = len(re.findall(r"CRITICAL", txt))
        high = len(re.findall(r"HIGH", txt))
        last = txt.strip().splitlines()[-1] if txt.strip() else ""
        lines.append(f"- CRITICAL hits: {crit}, HIGH hits: {high} (last line: {last[:120]})")
    else:
        lines.append("- no results yet (first scheduled run Sun 04:30)")

    # ── ghost containers + drift ──
    ghost = run("bash /home/rohit/.hermes/scripts/docker_ghost_check.sh", timeout=60)
    lines.append(section("Ghost containers / drift"))
    lines.append(f"- {ghost.splitlines()[-1] if ghost else '(ghost check unavailable)'}")

    # ── hop telemetry ──
    hop = run("curl -s -m 8 http://127.0.0.1:8083/v1/models -o /dev/null -w '%{http_code}'")
    lines.append(section("LLM front door"))
    lines.append(f"- hop gateway :8083/models → HTTP {hop or 'unreachable'}")

    report = "\n".join(lines)
    report_path = REPORT_DIR / f"weekly_health_{datetime.now():%Y%m%d}.md"
    report_path.write_text(report)

    # ── Telegram summary (compact) ──
    try:
        sys.path.insert(0, str(HH / "scripts"))
        from telegram_bridge import send_telegram
        body = "📊 **Weekly homelab health**\n" + report
        send_telegram(body, dedup_window=600)
    except Exception as e:
        print(f"WARN: telegram digest failed: {e}", file=sys.stderr)

    print(report)
    print(f"\nreport: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())