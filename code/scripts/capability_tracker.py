#!/usr/bin/env python3
"""capability_tracker.py — Tracks job usage, success rates, and durations.

Maintains a historical record of scheduler job runs and surfaces
pruning candidates for self_prune.py.

Reads: scheduler_state.json (per-job last run data)
Writes: state/capability_history.jsonl + state/capability_report.json
"""

import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path.home() / ".hermes"
HISTORY = HERMES / "state" / "capability_history.jsonl"
REPORT = HERMES / "state" / "capability_report.json"
SCHED_STATE = HERMES / "data" / "scheduler_state.json"
SCHED_SCRIPT = HERMES / "scripts" / "hermes_scheduler.py"

# Tags to never prune (core infrastructure)
PROTECTED_TAGS = {"maintenance", "memory", "monitor", "network", "backup"}
PROTECTED_JOBS = {
    "persona_morning", "persona_evening", "system_doctor", "debloat",  # just added
    "memory_sync", "self_correction", "self_modifier",
}

# Jobs retired because their scripts were removed (superseded by backup_all.py).
# Excluded from pruning stats to avoid stale high-failure noise.
RETIRED_JOBS = {
    "kopia_backup", "kopia_volumes", "traefik_sync",
}

# Only analyze run history within this window so pre-fix/stale failure noise
# (e.g. the archived-scripts era) does not keep jobs flagged as failing.
ANALYSIS_WINDOW_DAYS = 14


def read_scheduler_state():
    try:
        return json.loads(SCHED_STATE.read_text())
    except Exception:
        return {}


def read_job_definitions():
    """Parse scheduler script to extract job metadata (description, tags, enabled)."""
    jobs = {}
    try:
        import ast
        import sys
        sys.path.insert(0, str(SCHED_SCRIPT.parent))
        # Use ast to find Job calls
        tree = ast.parse(SCHED_SCRIPT.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Job":
                args = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                name = ""
                if node.args:
                    try:
                        name = node.args[0].value if isinstance(node.args[0], ast.Constant) else ""
                    except Exception:
                        name = ""
                if name:
                    jobs[name] = {
                        "description": getattr(args.get("description"), "value", ""),
                        "tags": [t.value for t in getattr(args.get("tags"), "elts", [])] if args.get("tags") else [],
                        "enabled": getattr(args.get("enabled"), "value", True),
                        "timeout": getattr(args.get("timeout"), "value", 300),
                    }
    except Exception:
        pass
    return jobs


def append_history(snapshot: dict):
    """Append a time-stamped snapshot of all job states to the history log."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "jobs": {},
    }
    for name, data in snapshot.items():
        if name in ("last_run", "jobs_run_count") or not isinstance(data, dict):
            continue
        entry["jobs"][name] = {
            "status": data.get("last_status", "unknown"),
            "elapsed": data.get("elapsed_seconds", 0),
            "returncode": data.get("returncode", -1),
        }
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY, "a") as f:
        f.write(json.dumps(entry) + "\n")


def build_report() -> dict:
    """Analyze history and build a capability report."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=ANALYSIS_WINDOW_DAYS)

    # Read history, keeping only snapshots within the analysis window
    history = []
    if HISTORY.exists():
        for line in HISTORY.read_text().strip().split("\n"):
            if line.strip():
                try:
                    snap = json.loads(line)
                except Exception:
                    continue
                try:
                    ts = datetime.fromisoformat(snap.get("ts", ""))
                except Exception:
                    continue
                if ts and ts >= cutoff:
                    history.append(snap)

    if not history:
        return {"report_ts": datetime.now().isoformat(), "jobs": {}, "prune_candidates": []}

    # Aggregate per job across all snapshots. Scheduler state carries the last
    # status forward between runs, so a repeated failure in consecutive
    # snapshots is the SAME run event. Count every snapshot as a run (healthy
    # jobs stay "active") but count a failure only when the status CHANGES
    # into a non-success state — preventing one stale failure from inflating
    # the rate across dozens of snapshots.
    job_stats = {}
    prev_status: dict[str, str] = {}
    for snap in history:
        for name, data in snap.get("jobs", {}).items():
            status = data.get("status", "unknown")
            if name not in job_stats:
                job_stats[name] = {"runs": 0, "failures": 0, "durations": [], "last_seen": "", "last_status": ""}
            job_stats[name]["runs"] += 1
            if status != prev_status.get(name):
                # New run event (status changed) -> may count as a failure
                if status != "success":
                    job_stats[name]["failures"] += 1
                prev_status[name] = status
                dur = data.get("elapsed", 0)
                if isinstance(dur, (int, float)):
                    job_stats[name]["durations"].append(dur)
                if status:
                    job_stats[name]["last_status"] = status
                job_stats[name]["last_seen"] = snap.get("ts", "")

    # Get job metadata
    job_defs = read_job_definitions()

    # Drop retired jobs and jobs no longer defined in the scheduler
    # (renamed/removed, e.g. weekly_optimize -> homelab_optimizer).
    job_stats = {n: s for n, s in job_stats.items()
                 if n not in RETIRED_JOBS and n in job_defs}

    # Build report
    report_jobs = {}
    prune_candidates = []

    for name, stats in sorted(job_stats.items()):
        runs = stats["runs"]
        failures = stats["failures"]
        avg_dur = sum(stats["durations"]) / len(stats["durations"]) if stats["durations"] else 0
        failure_rate = (failures / runs * 100) if runs > 0 else 0

        # Determine if this is a prune candidate
        reason = None
        job_def = job_defs.get(name, {})
        tags = job_def.get("tags", [])
        is_protected = any(t in PROTECTED_TAGS for t in tags) or name in PROTECTED_JOBS

        # Last seen parsing
        last_seen_days = None
        if stats["last_seen"]:
            try:
                last_seen = datetime.fromisoformat(stats["last_seen"])
                last_seen_days = (now - last_seen).total_seconds() / 86400
            except Exception:
                pass

        if not is_protected:
            if last_seen_days is not None and last_seen_days > 7 and runs < 10:
                reason = f"no significant activity in {last_seen_days:.0f}d ({runs} runs)"
            elif failure_rate > 50 and runs >= 5:
                reason = f"high failure rate ({failure_rate:.0f}% over {runs} runs)"
            elif runs < 3 and last_seen_days and last_seen_days > 3:
                reason = f"very few runs ({runs}) and old ({last_seen_days:.0f}d)"

        entry = {
            "runs": runs,
            "failures": failures,
            "failure_rate_pct": round(failure_rate, 1),
            "avg_duration_s": round(avg_dur, 2),
            "last_status": stats["last_status"],
            "last_seen": stats["last_seen"],
            "description": job_def.get("description", ""),
            "tags": tags,
            "enabled": job_def.get("enabled", True),
            "protected": is_protected,
            "prune_reason": reason,
        }
        report_jobs[name] = entry
        if reason:
            prune_candidates.append({"name": name, "reason": reason})

    report = {
        "report_ts": datetime.now().isoformat(),
        "total_jobs_tracked": len(report_jobs),
        "total_runs": sum(j["runs"] for j in report_jobs.values()),
        "total_failures": sum(j["failures"] for j in report_jobs.values()),
        "prune_candidates": prune_candidates,
        "jobs": report_jobs,
    }

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2))
    return report


def track():
    state = read_scheduler_state()
    append_history(state)
    report = build_report()

    pc = report.get("prune_candidates", [])
    summary = f"Tracked {report['total_jobs_tracked']} jobs ({report['total_runs']} runs)"
    if pc:
        summary += f", {len(pc)} prune candidates"
        for c in pc[:5]:
            summary += f"\n  - {c['name']}: {c['reason']}"
    print(summary)
    return report


if __name__ == "__main__":
    track()
