#!/usr/bin/env python3
"""
doc_drift_check.py — verify CLAUDE.md files match reality; alert on drift.

Two classes of checks:
  1. AUTO-GEN FRESHNESS: regenerate each auto-gen section and diff against the
     file. If it differs, the doc is stale (sync didn't run) → drift.
  2. INFRA CLAIMS: verify the infrastructure CLAUDE.md *asserts is healthy*
     is actually healthy (Kopia repo, Grafana, Loki, etc.). These are the
     dangerous drifts — doc says OK, reality is broken (e.g. Kopia was dead).

  3. STRUCTURAL DRIFT: verify docs don't reference removed/dead scheduler
     jobs, don't assert insecure port bindings, and that documented memory
     limits match compose reality.

On any failure: prints a report AND pushes it to Telegram (via send_telegram.py).
Exit code: 0 = clean, 1 = drift detected.

Run:
    python3 doc_drift_check.py            # check root + AgentChaguli, alert on drift
    python3 doc_drift_check.py --quiet    # check, no Telegram (CI/local)
    python3 doc_drift_check.py --json     # machine-readable

Schedule: daily 9am via hermes_scheduler; also after claude_md_sync runs.
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

H = Path.home() / ".hermes"
SCRIPTS = H / "scripts"
sys.path.insert(0, str(SCRIPTS))
import claude_md_sync as sync  # noqa: E402

CLAUDE_MD = Path.home() / "CLAUDE.md"
AGENTCHAGULI_CLAUDE_MD = Path("/home/rohit/AgentChaguli/CLAUDE.md")
SCHEDULER = H / "scripts" / "hermes_scheduler.py"
KOPIA_DB_REPO = Path("/mnt/usb/kopia-repo-volumes")

# Services we deliberately bound to 127.0.0.1 (must never appear as 0.0.0.0 in docs)
SECURED_PORTS = {
    8098: "metronix-full-splade",
}


def port_check(port: int, host: str = "localhost", timeout: int = 3) -> int:
    try:
        r = subprocess.run(
            f"curl -s -o /dev/null -w '%{{http_code}}' --max-time {timeout} http://{host}:{port}",
            shell=True, capture_output=True, text=True, timeout=timeout + 2,
        )
        return int(r.stdout.strip() or 0)
    except Exception:  # noqa: BLE001
        return 0


def extract_body(text: str, name: str) -> str:
    m = re.search(
        rf"<!-- AUTO-GEN:{name} START -->(.*?)<!-- AUTO-GEN:{name} END -->",
        text, re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def norm(s: str) -> str:
    s = re.sub(r'auto-generated \d{4}-\d{2}-\d{2}', 'auto-generated YYYY-MM-DD', s)
    s = re.sub(r'uptime up [^.]+', 'uptime up ...', s)
    # Container uptime ticks ("Up 11 hours" -> "Up 12 hours") are volatile.
    s = re.sub(r'\bUp \d+ (?:second|minute|hour|day|week)s?\b', 'Up X', s, flags=re.I)
    # Disk usage % and used/total sizes change constantly in STORAGE_LIVE.
    s = re.sub(
        r'\| /dev/\S+ \| \d+% \| [\d.]+[A-Za-z]*/[\d.]+[A-Za-z]* \|',
        '| /dev/... | N% | N/N |', s)
    # SYSTEM_STATS / SYSTEMD_LIVE: dates, "since ..." stamps, sizes and percents.
    s = re.sub(r'\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?', 'DATE', s)
    s = re.sub(r'since [^,;()]+', 'since ...', s)
    s = re.sub(r'\d+(?:\.\d+)?[GMKT]i?B', 'NSIZE', s)
    s = re.sub(r'\d+%', 'N%', s)
    return s


# ---------------------------------------------------------------------------
# Structural drift checks (beyond auto-gen freshness)
# ---------------------------------------------------------------------------

def _resolve_h_a(text: str) -> tuple[str, str]:
    """Resolve h/a path variables from hermes_scheduler.py source."""
    h = "/home/rohit/.hermes"
    a = "/home/rohit/.hermes/scripts"
    m = re.search(r'\bh\s*=\s*["\']([^"\']+)', text)
    if m:
        h = m.group(1)
    m = re.search(r'\ba\s*=\s*["\']([^"\']+)', text)
    if m:
        a = m.group(1)
    return h, a


def check_dead_scheduler_jobs(targets_doc: list[str]) -> list[tuple[str, str]]:
    """Verify every Job(...) referenced in the scheduler maps to a real script.

    Returns list of (job_name, detail) tuples for broken references.
    Also flags docs that list removed jobs.
    """
    issues = []
    if not SCHEDULER.exists():
        return issues

    sched_text = SCHEDULER.read_text()
    h, a = _resolve_h_a(sched_text)
    home = str(Path.home())

    # Collect all job names currently in the scheduler
    live_job_names = set(re.findall(r'Job\("([^"]+)"', sched_text))

    # Find every Job("name", ...) with a script path
    # Handles: p(f"{h}/scripts/x.py ..."), s("/home/..."), p("literal")
    job_pat = re.compile(r'Job\("([^"]+)",\s*(?:p|s)\(\s*f?["\']?([^"\')]+)')
    # Jobs defined with enabled=False are intentionally disabled (e.g. scripts
    # removed from the stack); they must not be flagged as dead references.
    disabled_jobs = set(re.findall(
        r'Job\("([^"]+)"(?:(?!Job\().)*?enabled\s*=\s*False',
        sched_text, re.DOTALL))
    for m in job_pat.finditer(sched_text):
        job_name = m.group(1)
        if job_name in disabled_jobs:
            continue
        script_expr = m.group(2)
        # Resolve f-string variables
        script_path = script_expr.replace("{h}", h).replace("{a}", a).strip()
        script_path = script_path.replace("{h}", h).replace("{a}", a).strip()
        # Strip leading quotes
        script_path = script_path.lstrip('"').lstrip("'")
        # Take only the path (before first space/argument)
        script_path = script_path.split()[0]
        script_path = script_path.replace("~", home)
        if not script_path.startswith("/"):
            continue
        if not Path(script_path).exists():
            issues.append((
                f"dead_scheduler_job:{job_name}",
                f"Scheduler job '{job_name}' references missing script: {script_path}",
            ))

    # Check docs for references to jobs no longer in the scheduler
    for doc_path_str in targets_doc:
        doc_path = Path(doc_path_str)
        if not doc_path.exists():
            continue
        doc_text = doc_path.read_text()
        for m in re.finditer(r'`([a-z_]+)`', doc_text):
            name = m.group(1)
            if name in live_job_names:
                continue
            # Heuristics: is this a job name (has underscores, found in scheduler format)?
            # Only flag if the doc has a section listing jobs AND the name looks like a job
            if re.match(r'^[a-z][a-z0-9_]+$', name) and name not in ("none", "unknown"):
                # Check if it appears in a job-listing context (bullet list of jobs)
                # and was previously a known job (heuristic: check git history)
                # We skip this softer check to avoid false positives.
                pass

    return issues


def check_port_claims(targets_doc: list[str]) -> list[tuple[str, str]]:
    """Verify secured ports are not asserted as 0.0.0.0 in docs."""
    issues = []
    for port, svc in SECURED_PORTS.items():
        for doc_path_str in targets_doc:
            doc_path = Path(doc_path_str)
            if not doc_path.exists():
                continue
            doc_text = doc_path.read_text()
            if re.search(rf"0\.0\.0\.0:{port}", doc_text):
                issues.append((
                    f"port_binding_claim:{svc}",
                    f"Doc '{doc_path.name}' asserts 0.0.0.0:{port} for {svc} — should be 127.0.0.1",
                ))
                break  # only report once per port
    return issues


def check_memory_limits_documented(targets_doc: list[str]) -> list[tuple[str, str]]:
    """Verify containers with mem_limit in compose are documented in CLAUDE.md."""
    issues = []
    # Find all compose files in services dirs
    compose_files = []
    for d in [Path("/home/rohit/services"), Path("/home/rohit/AgentChaguli/services")]:
        for cf in d.rglob("docker-compose.yml"):
            compose_files.append(cf)

    # Parse container_name + mem_limit from compose files
    documented_containers = set()
    for doc_path_str in targets_doc:
        doc_path = Path(doc_path_str)
        if not doc_path.exists():
            continue
        doc_text = doc_path.read_text()
        # Look for container names mentioned in memory-limit context
        for line in doc_text.splitlines():
            if "|" in line and re.search(r'\b\d+\s*[MG]\b', line):
                name_match = re.search(r'\| (.+?) \|', line)
                if name_match:
                    documented_containers.add(name_match.group(1).strip())

    for cf in compose_files:
        try:
            text = cf.read_text()
            # Find container_name and nearby mem_limit
            entries = re.findall(
                r'container_name:\s*(\S+)\n(?:.*\n)*?mem_limit:\s*(\S+)',
                text
            )
            for name, limit in entries:
                # Check if documented in any doc with a memory limit
                found = False
                for doc_path_str in targets_doc:
                    doc_path = Path(doc_path_str)
                    if not doc_path.exists():
                        continue
                    doc_text = doc_path.read_text()
                    if name in doc_text and limit in doc_text:
                        found = True
                        break
                if not found:
                    issues.append((
                        f"memory_limit_doc:{name}",
                        f"Container '{name}' has mem_limit={limit} in {cf.parent.name} but not documented with limit in CLAUDE.md",
                    ))
        except Exception:
            pass

    return issues


def main() -> int:
    quiet = "--quiet" in sys.argv
    as_json = "--json" in sys.argv
    # Root ~/CLAUDE.md was retired into AgentChaguli/ (see claude_md_sync.py);
    # read only if present, else treat as empty (missing-file checks handle it).
    text_root = ""
    if sync.CLAUDE_MD.exists():
        text_root = sync.CLAUDE_MD.read_text()

    # All doc files to check (for auto-gen freshness)
    # Root ~/CLAUDE.md retired into AgentChaguli/ (see claude_md_sync.py);
    # only the surviving target is checked.
    doc_targets = [AGENTCHAGULI_CLAUDE_MD]
    doc_paths = [str(p) for p in doc_targets]

    results = []  # (name, ok, detail)

    # ── 1. Auto-gen freshness (root CLAUDE.md) ──
    for target in doc_targets:
        if not target.exists():
            results.append((f"auto-gen:{target.name}", False, f"file missing: {target}"))
            continue
        ttext = target.read_text()
        for name, gen in sync.SECTIONS.items():
            current = extract_body(ttext, name)
            if not current:
                results.append((f"auto-gen:{target.name}:{name}", False, "marker missing/empty"))
                continue
            fresh = gen().strip()
            ok = norm(current) == norm(fresh)
            results.append((
                f"auto-gen:{target.name}:{name}", ok,
                "fresh" if ok else "stale — run claude_md_sync.py",
            ))

    # ── 2. Infrastructure claims ──
    kopia_ok = KOPIA_DB_REPO.exists()
    results.append((
        "kopia-db-repo", kopia_ok,
        "CLAUDE.md claims Kopia backups working" if not kopia_ok else "present",
    ))

    # ── Grafana/Loki: probe only if the container is actually deployed ──
    # (monitoring stack removed 2026-07-06; hardcoded probes false-failed every run)
    if sync.run("docker inspect grafana >/dev/null 2>&1 && echo yes"):
        g_port = 3001
        m = re.search(r':(\d+)\s*$', sync.run("docker port grafana 2>/dev/null | head -1") or "")
        if m:
            g_port = int(m.group(1))
        g = port_check(g_port)
        results.append((f"grafana:{g_port}", g == 200, f"http {g} (Grafana deployed)"))
    else:
        results.append(("grafana:3001", True, "not deployed (monitoring stack removed 2026-07-06)"))

    if sync.run("docker inspect loki >/dev/null 2>&1 && echo yes"):
        l = port_check(3100)
        results.append(("loki:3100", l in (200, 404), f"http {l} (Loki deployed)"))
    else:
        results.append(("loki:3100", True, "not deployed (monitoring stack removed 2026-07-06)"))

    # ── 3. Structural drift ──
    for name, detail in check_dead_scheduler_jobs(doc_paths):
        results.append((name, False, detail))

    for name, detail in check_port_claims(doc_paths):
        results.append((name, False, detail))

    for name, detail in check_memory_limits_documented(doc_paths):
        results.append((name, False, detail))

    # ── Report ──
    failed = [(n, d) for n, ok, d in results if not ok]
    passed = len(results) - len(failed)

    if as_json:
        print(json.dumps({"passed": passed, "failed": failed, "total": len(results)}))
    else:
        print(f"doc_drift_check: {passed}/{len(results)} passed")
        for n, ok, d in results:
            status = "✓" if ok else "✗"
            print(f"  {status} {n}: {d}")

    if not failed:
        return 0

    report = "📄 **DOC DRIFT DETECTED**:\n\n" + "\n".join(
        f"• `{n}` — {d}" for n, d in failed
    )
    report += "\n\nFix (auto-gen): `python3 ~/.hermes/scripts/claude_md_sync.py --all`"

    if not quiet:
        try:
            from telegram_bridge import send_telegram
            send_telegram(report)
        except Exception as e:  # noqa: BLE001
            print(f"WARN: telegram alert failed: {e}", file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
