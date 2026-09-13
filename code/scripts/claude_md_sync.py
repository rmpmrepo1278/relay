#!/usr/bin/env python3
"""
claude_md_sync.py — regenerate auto-generated sections of CLAUDE.md files from LIVE state.

Philosophy: docs are GENERATED from reality, never hand-maintained. Reality is the
single source of truth; CLAUDE.md is just a rendered view of it.

Sections are delimited by HTML-comment markers:
    <!-- AUTO-GEN:NAME START -->
    ... generated content (replaced on every run) ...
    <!-- AUTO-GEN:NAME END -->

Only content BETWEEN markers is replaced. Hand-written prose is never touched.

By default syncs ALL target files (root ~/CLAUDE.md + AgentChaguli/CLAUDE.md).
Use --target PATH to sync a single file, or --check for CI guard mode.

Run:
    python3 claude_md_sync.py            # regenerate all auto-gen sections in all targets
    python3 claude_md_sync.py --dry-run  # print what WOULD change, write nothing
    python3 claude_md_sync.py --check    # exit 1 if any marker is missing (CI guard)
    python3 claude_md_sync.py --target /path/to/CLAUDE.md  # single file

Schedule: daily 2am via hermes_scheduler; also call after any infra change.
"""
from __future__ import annotations
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CLAUDE_MD = Path.home() / "CLAUDE.md"
AGENTCHAGULI_CLAUDE_MD = Path("/home/rohit/AgentChaguli/CLAUDE.md")
SCHEDULER = Path.home() / ".hermes" / "scripts" / "hermes_scheduler.py"

# All files with auto-gen markers that should be kept in sync.
# Root ~/CLAUDE.md was retired into AgentChaguli/; missing targets are
# skipped gracefully (docs are generated from reality, not asserted).
TARGETS = [Path("/home/rohit/AgentChaguli/CLAUDE.md")]


def run(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"(error: {e})"


# ---------------------------------------------------------------------------
# Generators — each returns the markdown body for its section
# ---------------------------------------------------------------------------

def gen_system_stats() -> str:
    containers = run("docker ps -q 2>/dev/null | wc -l") or "0"
    user_svcs = run("systemctl --user list-units --type=service --state=running --no-legend 2>/dev/null | wc -l") or "0"
    sys_svcs = run("systemctl list-units --type=service --state=running --no-legend 2>/dev/null | wc -l") or "0"
    disk = run("df -h / | awk 'NR==2{print $5 \" used (\" $3 \"/\" $2 \")\"}'")

    uptime = run("uptime -p 2>/dev/null") or "unknown"
    return (
        f"**Live state (auto-generated {datetime.now():%Y-%m-%d}):** "
        f"{containers} Docker containers running · {user_svcs} user + {sys_svcs} systemd services active · "
        f"root disk {disk} · uptime {uptime}."
    )


def gen_containers() -> str:
    out = run('docker ps --format "{{.Names}}|{{.Status}}|{{.Ports}}" 2>/dev/null')
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = (line.split("|") + ["", "", ""])[:3]
        name, status, ports = parts
        ports = (ports[:90] + "…") if len(ports) > 90 else ports
        rows.append(f"| {name} | {status} | {ports} |")
    body = "\n".join(rows) if rows else "| _none running_ | — | — |"
    return f"| Container | Status | Ports |\n|-----------|--------|-------|\n{body}"


def gen_cron_jobs() -> str:
    count = run(f'grep -c \'Job("\' "{SCHEDULER}" 2>/dev/null') or "0"
    names = run(f'grep -oE \'Job\\("[a-z_]+\"\' "{SCHEDULER}" 2>/dev/null | sed -E \'s/Job\\("//; s/"//\' | sort -u')
    bullets = "\n".join(f"- `{n}`" for n in names.splitlines() if n.strip())
    return (
        f"Managed by unified scheduler `hermes_scheduler.py --daemon` (replaces legacy cron): "
        f"**{count} jobs**.\n\n{bullets}"
    )


def gen_systemd_live() -> str:
    usr = run("systemctl --user list-units --type=service --state=running --no-legend 2>/dev/null | awk '{print $1}'")
    sys_ = run("systemctl list-units --type=service --state=running --no-legend 2>/dev/null | awk '{print $1}'")
    u = "\n".join(f"- `{s}`" for s in usr.splitlines() if s.strip())
    s = "\n".join(f"- `{s}`" for s in sys_.splitlines() if s.strip())
    return f"**User services (active):**\n{u}\n\n**System services (active):**\n{s}"


def gen_storage_live() -> str:
    out = run("df -h / /mnt/usb 2>/dev/null | awk 'NR>1{print $1\"|\"$5\"|\"$3\"/\"$2}'")
    rows = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) >= 3:
            rows.append(f"| {parts[0]} | {parts[1]} | {parts[2]} |")
    body = "\n".join(rows) if rows else "| _no data_ | — | — |"
    return f"| Filesystem | Used | Total |\n|-----------|------|-------|\n{body}"


# Section registry: marker name -> generator
SECTIONS = {
    "SYSTEM_STATS": gen_system_stats,
    "CONTAINERS": gen_containers,
    "CRON_JOBS": gen_cron_jobs,
    "SYSTEMD_LIVE": gen_systemd_live,
    "STORAGE_LIVE": gen_storage_live,
}

MARKER_RE = re.compile(
    r"<!-- AUTO-GEN:(?P<name>\w+) START -->.*?<!-- AUTO-GEN:\1 END -->",
    re.DOTALL,
)


def _replace_named(text: str, name: str, body: str) -> tuple[str, int]:
    pat = re.compile(
        rf"<!-- AUTO-GEN:{name} START -->.*?<!-- AUTO-GEN:{name} END -->",
        re.DOTALL,
    )
    new_text, n = pat.subn(
        f"<!-- AUTO-GEN:{name} START -->\n{body}\n<!-- AUTO-GEN:{name} END -->",
        text,
    )
    return new_text, n


def sync(target: Path = CLAUDE_MD, dry_run: bool = False, check: bool = False) -> int:
    """Sync auto-gen sections in *target* (defaults to root CLAUDE.md)."""
    if not target.exists():
        print(f"WARN: skipping missing target {target}", file=sys.stderr)
        return 0
    text = target.read_text()
    found = set(MARKER_RE.findall(text))
    missing = [name for name in SECTIONS if name not in found]

    if check:
        if missing:
            print(f"MISSING MARKERS in {target}: {', '.join(missing)}", file=sys.stderr)
            return 1
        print(f"OK: all auto-gen markers present in {target}")
        return 0

    if missing:
        print(f"WARN: skipping missing markers in {target}: {', '.join(missing)}", file=sys.stderr)

    new_text = text
    changed = []
    for name, gen in SECTIONS.items():
        if name in missing:
            continue
        body = gen().rstrip()
        new_text, n = _replace_named(new_text, name, body)
        if n:
            changed.append(name)

    if dry_run:
        print(f"=== DRY RUN — no changes written to {target} ===")
        for name in changed:
            print(f"\n--- {name} (would regenerate) ---")
        print(f"\nSections that would update: {', '.join(changed) or 'none'}")
        return 0

    target.write_text(new_text)
    print(f"Synced {len(changed)} section(s) in {target.name}: {', '.join(changed)}")
    return 0


def sync_all(dry_run: bool = False, check: bool = False) -> int:
    """Sync every file in TARGETS."""
    rc = 0
    for target in TARGETS:
        r = sync(target, dry_run=dry_run, check=check)
        rc = max(rc, r)
    return rc


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    check = "--check" in sys.argv
    target_arg = None
    if "--target" in sys.argv:
        idx = sys.argv.index("--target")
        target_arg = Path(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else None
    all_flag = "--all" in sys.argv

    if target_arg:
        sys.exit(sync(target=target_arg, dry_run=dry, check=check))
    elif all_flag or not (dry or check):
        # Default: sync all targets (backward compat — bare invocation syncs all)
        sys.exit(sync_all(dry_run=dry, check=check))
    else:
        sys.exit(sync_all(dry_run=dry, check=check))
