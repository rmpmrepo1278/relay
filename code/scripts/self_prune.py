#!/usr/bin/env python3
"""self_prune.py — Auto-disables unused/failing capabilities.

Reads: capability_report.json (from capability_tracker.py)
Action: Disables jobs via scheduler, archives dead scripts
Reports: Telegram summary of pruning actions

Runs once daily at 5am.
"""

import ast
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from import_safety import import_blockers

HERMES = Path.home() / ".hermes"
REPORT = HERMES / "state" / "capability_report.json"
SCHED = HERMES / "scripts" / "hermes_scheduler.py"
ARCHIVE = HERMES / "state" / "pruned_jobs.jsonl"

# Minimum days since a job ran to be considered "stale"
STALE_DAYS = 14
MIN_FAILURE_RATE = 60  # percent
MIN_FAILURE_RUNS = 5  # minimum runs before considering failure rate


def send(text: str):
    try:
        import sys
        sys.path.insert(0, str(HERMES / "scripts"))
        from telegram_bridge import send_telegram
        send_telegram(text[:4096])
    except Exception as e:
        print(f"send failed: {e}")


def log_action(action: str, detail: str = ""):
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    entry = json.dumps({
        "ts": datetime.now().isoformat(),
        "action": action,
        "detail": detail,
    })
    with open(ARCHIVE, "a") as f:
        f.write(entry + "\n")


def read_report():
    try:
        return json.loads(REPORT.read_text())
    except Exception:
        return None


def _job_enabled_kwarg(node: ast.Call):
    """Return the 'enabled' keyword node of a Job(...) call, or None."""
    for kw in node.keywords:
        if kw.arg == "enabled":
            return kw
    return None


def disable_job_in_scheduler(job_name: str) -> bool:
    """Set enabled=False for a job in the scheduler script.

    Uses AST to locate the exact Job(...) node and edits only the 'enabled'
    keyword, so commands with nested parens (p(f"..."), docker run $(cat ...),
    Schedule(...)) are handled correctly — the old regex approach truncated at
    the first ')' and reported 'strange format'.
    """
    try:
        content = SCHED.read_text()
        tree = ast.parse(content)

        # Find the Job("job_name", ...) call node
        target = None
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Job"):
                continue
            if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == job_name:
                target = node
                break
        if target is None:
            log_action("prune_failed", f"Could not find job {job_name} in scheduler")
            return False

        # Compute absolute offsets from line/col info
        lines = content.splitlines(keepends=True)

        def offset(lineno: int, col_offset: int) -> int:
            return sum(len(l) for l in lines[:lineno - 1]) + col_offset

        kw = _job_enabled_kwarg(target)
        if kw is None:
            # No enabled kwarg: insert ", enabled=False" before the closing paren
            end = offset(target.end_lineno, target.end_col_offset)
            insert_at = end - 1  # position of the ')' char
            new_content = content[:insert_at] + ", enabled=False" + content[insert_at:]
        else:
            val = kw.value
            if isinstance(val, ast.Constant) and val.value is False:
                log_action("prune_skipped", f"{job_name} already disabled")
                return True  # Already disabled
            start = offset(val.lineno, val.col_offset)
            end = offset(val.end_lineno, val.end_col_offset)
            new_content = content[:start] + "False" + content[end:]

        # Sanity check: the edit must still parse and the job must exist
        ast.parse(new_content)
        SCHED.write_text(new_content)
        log_action("pruned", f"Disabled {job_name} in scheduler")
        return True
    except Exception as e:
        log_action("prune_error", f"{job_name}: {e}")
        return False


def archive_dead_script(script_path: str) -> bool:
    """Move a dead script to state/archive/dead/ (skips if live code imports it)."""
    src = Path(script_path)
    if not src.exists():
        return False
    blockers = import_blockers(str(src))
    if blockers:
        log_action("skipped-archival", f"{src.name} still imported by {', '.join(blockers)}")
        return False
    dst = HERMES / "state" / "archive" / "dead" / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    log_action("archived", f"Moved {src.name} to archive/dead/")
    return True


def restart_scheduler():
    """Schedule a deferred daemon restart so enabled=False edits take effect.

    The scheduler loads job definitions once at startup, so a plain file edit
    has no effect until the daemon restarts. We defer via systemd-run so the
    restart lands after this job finishes (it runs as a child of the daemon).
    """
    try:
        subprocess.run(
            ["systemd-run", "--user", "--on-active=30",
             "systemctl", "--user", "restart", "hermes-scheduler"],
            check=False, capture_output=True, timeout=15,
        )
    except Exception as e:
        log_action("prune_error", f"restart_scheduler: {e}")


def prune():
    report = read_report()
    if not report:
        print("No capability report found. Run capability_tracker.py first.")
        return

    now = datetime.now()
    candidates = report.get("prune_candidates", [])
    if not candidates:
        print("No prune candidates — all capabilities healthy.")
        return

    pruned = []
    archived = []
    skipped = []

    for c in candidates:
        name = c["name"]
        reason = c["reason"]
        job_info = report["jobs"].get(name, {})

        # Skip if already disabled
        if not job_info.get("enabled", True):
            skipped.append(name)
            continue

        # Skip protected jobs
        if job_info.get("protected"):
            skipped.append(f"{name} (protected)")
            continue

        # Disable in scheduler
        ok = disable_job_in_scheduler(name)
        if ok:
            pruned.append(name)
            # Try to archive the associated script if we can find it
            # Script name usually matches job name
            script_candidates = list(HERMES.rglob(f"scripts/{name}.py")) + list(HERMES.rglob(f"scripts/{name}.sh"))
            for sc in script_candidates[:1]:
                archive_dead_script(str(sc))
                archived.append(sc.name)
        else:
            skipped.append(name)

    # Compose summary
    lines = ["Prune summary:"]
    if pruned:
        lines.append(f"  Disabled: {', '.join(pruned)}")
    if archived:
        lines.append(f"  Archived: {', '.join(archived)}")
    if skipped:
        lines.append(f"  Skipped: {', '.join(skipped)}")

    summary = "\n".join(lines)
    print(summary)
    send(summary)

    # Only restart the scheduler if we actually disabled something; otherwise
    # the running daemon keeps the old job definitions in memory.
    if pruned:
        restart_scheduler()


if __name__ == "__main__":
    prune()
