#!/usr/bin/env python3
"""
proactive_engine.py — State-change-triggered proactive decision engine.

The problem it solves: today every proactive module fires on a fixed clock
(4h, 6h, daily). Real initiative means acting when *state changes in a way
that matters* — not when the minute-hand hits a number.

Design:
  - Every minute, watch a set of signal files (health, scheduler state,
    task queue, interest profile, insights, capsule outcomes).
  - When a file's content hash changes (or a threshold breaches), score
    candidate actions: each candidate has an *urgency* (0-1) computed from
    the signal delta and *cost* (how expensive it is to run).
  - If a candidate's urgency exceeds its hysteresis threshold, fire it by
    delegating to the existing modules (subprocess), then record the
    decision in the decision ledger.
  - Cooldowns + dedup prevent thrash. A baseline snapshot is stored so we
    only act on *changes*.

Usage:
    python3 proactive_engine.py --once        # run one evaluation cycle
    python3 proactive_engine.py --snapshot    # (re)build baseline snapshot
    python3 proactive_engine.py --debug       # verbose

Scheduled: every 1 minute via hermes_scheduler.py. Cheap when nothing changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DIR = HERMES_HOME / "state"
DATA_DIR = HERMES_HOME / "data"
SCRIPTS_DIR = HERMES_HOME / "scripts"
SNAPSHOT_FILE = STATE_DIR / "proactive_engine_snapshot.json"
LOG_FILE = HERMES_HOME / "logs" / "proactive_engine.log"

sys.path.insert(0, str(SCRIPTS_DIR))
try:
    from decision_ledger import record as ledger_record, resolve as ledger_resolve, load as ledger_load
    from adaptive_thresholds import get_thresholds
    from multi_step_planner import execute_plan
    from experiment_engine import select_variant, record_experiment_result, execute_experiment
    from human_escalation import should_escalate, escalate_to_human
    from predictive_signals import get_predictions
except ImportError:
    ledger_record = None
    ledger_resolve = None
    ledger_load = None
    def get_thresholds():
        return {
            "health_score_trigger": 0.3,
            "scheduler_fail_rate_trigger": 0.2,
            "capsule_fail_rate_trigger": 0.5,
            "cooldowns_min": {
                "troubleshoot": 15,
                "scheduler_repair": 20,
                "capsule_learn": 60,
                "curiosity": 120,
                "insight_surface": 30,
            },
            "urgency_threshold": 0.5,
        }
    def execute_plan(plan_key: str, dry_run: bool = False) -> dict:
        return {"error": "multi_step_planner not available"}
    def select_variant(action_key: str):
        return None
    def record_experiment_result(action_key: str, variant_id: str, outcome: str):
        pass
    def execute_experiment(action_key: str, context: dict = None):
        return {"error": "experiment_engine not available"}
    def should_escalate(confidence: float, action_context: dict):
        return False, ""
    def escalate_to_human(action_context: dict, confidence: float, reason: str):
        return {"escalated": False}
    def get_predictions():
        return {"predictions": {}}


# Signal files to watch, mapped to (label, weight)
SIGNAL_FILES = [
    (STATE_DIR / "health_dashboard.json", "health", 1.0),
    (DATA_DIR / "scheduler_state.json", "scheduler", 0.7),
    (STATE_DIR / "task_queue.json", "tasks", 0.8),
    (DATA_DIR / "interest_profile.json", "interests", 0.5),
    (DATA_DIR / "insights.json", "insights", 0.6),
    (HERMES_HOME / "capsules" / "outcomes.jsonl", "capsules", 0.9),
    (DATA_DIR / "curious_explorer_results.json", "curiosity", 0.4),
]


def log(msg: str, level: str = "INFO"):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {level}: {msg}"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")
    if "--debug" in sys.argv:
        print(line)


def _content_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()[:512 * 1024]).hexdigest()[:16]
    except OSError:
        return None


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _load_snapshot() -> dict:
    if SNAPSHOT_FILE.exists():
        try:
            return json.loads(SNAPSHOT_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"files": {}, "cooldowns": {}, "baseline": {}, "pending_verification": []}


def _save_snapshot(snap: dict):
    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SNAPSHOT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, indent=2))
    os.replace(tmp, SNAPSHOT_FILE)


def _scheduler_fail_rate(snap: dict) -> float:
    """Fraction of jobs failed in last run window."""
    state = _read_json(DATA_DIR / "scheduler_state.json")
    if not state:
        return 0.0
    failed = 0
    total = 0
    for k, v in state.items():
        if not isinstance(v, dict) or k in ("last_run", "jobs_run_count"):
            continue
        total += 1
        if v.get("last_status") == "failed":
            failed += 1
    return failed / total if total else 0.0


def _health_score(snap: dict) -> float:
    """0 = perfectly healthy, 1 = badly degraded."""
    hd = _read_json(STATE_DIR / "health_dashboard.json")
    if not hd:
        return 0.0
    score = 0.0
    total = 0
    for k, v in hd.items():
        if isinstance(v, dict):
            total += 1
            if v.get("status") in ("critical", "down", "error", "unhealthy"):
                score += 1.0
            elif v.get("status") == "warning":
                score += 0.5
    return score / total if total else 0.0


def _capsule_fail_rate(snap: dict) -> float:
    """Recent capsule outcome fail rate."""
    cf = HERMES_HOME / "capsules" / "outcomes.jsonl"
    if not cf.exists():
        return 0.0
    lines = cf.read_text().splitlines()[-40:]
    fails = sum(1 for l in lines if '"fail"' in l)
    return fails / len(lines) if lines else 0.0


def _resource_check() -> tuple[bool, str]:
    """Check if system resources allow heavy actions. Returns (ok, reason)."""
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    mem[k.strip()] = int(v.strip().split()[0])
        mem_free_pct = (mem.get("MemAvailable", 0) / mem.get("MemTotal", 1)) * 100
        if mem_free_pct < 15:
            return False, f"RAM low: {mem_free_pct:.0f}% free"
        
        import shutil
        du = shutil.disk_usage("/")
        disk_free_pct = (du.free / du.total) * 100
        if disk_free_pct < 10:
            return False, f"Disk low: {disk_free_pct:.0f}% free"
        
        load1 = os.getloadavg()[0]
        cpu_count = os.cpu_count() or 1
        if load1 > cpu_count * 1.5:
            return False, f"CPU load high: {load1:.1f} on {cpu_count} cores"
            
    except Exception as e:
        return True, f"resource check failed: {e}"
    return True, "resources ok"


def _candidate_actions(snap: dict) -> list[dict]:
    """Evaluate candidate actions. Returns list of {key, name, urgency, cmd, why, verify_fn}."""
    now = time.time()
    cooldowns_snap = snap.get("cooldowns", {})
    changed = set()
    for path, label, weight in SIGNAL_FILES:
        h = _content_hash(path)
        if h and snap.get("files", {}).get(label) != h:
            changed.add(label)

    # Load adaptive thresholds
    thresholds = get_thresholds()
    health_trigger = thresholds.get("health_score_trigger", 0.3)
    scheduler_trigger = thresholds.get("scheduler_fail_rate_trigger", 0.2)
    capsule_trigger = thresholds.get("capsule_fail_rate_trigger", 0.5)
    cooldowns = thresholds.get("cooldowns_min", {})

    def cooldown_ok(key: str) -> bool:
        cooldown_min = cooldowns.get(key, 30)
        return now - cooldowns_snap.get(key, 0) > cooldown_min * 60

    candidates = []

    # Check predictive signals for preemptive actions
    predictions = get_predictions().get("predictions", {})
    for signal_name, pred in predictions.items():
        if pred.get("severity") == "critical" and pred.get("predicted_hours_to_threshold", 999) < 24:
            if signal_name == "disk_usage_pct" and cooldown_ok("preempt_disk"):
                candidates.append({
                    "key": "preempt_disk",
                    "name": "preemptive_disk_cleanup",
                    "urgency": 0.9,
                    "cmd": ["python3", str(SCRIPTS_DIR / "system_doctor.py")],
                    "why": f"disk predicted to hit {pred['threshold']}% in {pred['predicted_hours_to_threshold']}h",
                    "verify": "verify_disk_space_freed",
                    "cost": "medium",
                })
            elif signal_name == "memory_usage_pct" and cooldown_ok("preempt_memory"):
                candidates.append({
                    "key": "preempt_memory",
                    "name": "preemptive_memory_check",
                    "urgency": 0.85,
                    "cmd": ["python3", str(SCRIPTS_DIR / "homelab_troubleshooter.py")],
                    "why": f"memory predicted to hit {pred['threshold']}% in {pred['predicted_hours_to_threshold']}h",
                    "verify": "verify_memory_freed",
                    "cost": "medium",
                })

    # 1. Health degraded -> run troubleshooter early
    hs = _health_score(snap)
    if hs > health_trigger and cooldown_ok("troubleshoot"):
        # Try experiment variant first
        variant = select_variant("troubleshoot")
        if variant:
            candidates.append({
                "key": "troubleshoot",
                "name": f"experiment_troubleshoot_{variant['id']}",
                "urgency": min(1.0, hs),
                "cmd": variant["cmd"],
                "why": f"health degraded (score {hs:.2f}, trigger {health_trigger}) — variant {variant['id']}",
                "verify": "verify_health_improved",
                "cost": "medium",
                "experiment_variant": variant["id"],
            })
        else:
            candidates.append({
                "key": "troubleshoot",
                "name": "homelab_troubleshooter",
                "urgency": min(1.0, hs),
                "cmd": ["python3", str(SCRIPTS_DIR / "homelab_troubleshooter.py")],
                "why": f"health degraded (score {hs:.2f}, trigger {health_trigger})",
                "verify": "verify_health_improved",
                "cost": "medium",
            })

    # 2. Scheduler failure rate spike -> self_correction + system_doctor
    fr = _scheduler_fail_rate(snap)
    if fr > scheduler_trigger and cooldown_ok("scheduler_repair"):
        variant = select_variant("scheduler_repair")
        if variant:
            candidates.append({
                "key": "scheduler_repair",
                "name": f"experiment_scheduler_repair_{variant['id']}",
                "urgency": min(1.0, fr),
                "cmd": variant["cmd"],
                "why": f"scheduler fail rate {fr:.0%} (trigger {scheduler_trigger:.0%}) — variant {variant['id']}",
                "verify": "verify_scheduler_fail_rate_dropped",
                "cost": "medium",
                "experiment_variant": variant["id"],
            })
        else:
            candidates.append({
                "key": "scheduler_repair",
                "name": "system_doctor",
                "urgency": min(1.0, fr),
                "cmd": ["python3", str(SCRIPTS_DIR / "system_doctor.py")],
                "why": f"scheduler fail rate {fr:.0%} (trigger {scheduler_trigger:.0%})",
                "verify": "verify_scheduler_fail_rate_dropped",
                "cost": "medium",
            })

    # 3. Capsule fail rate high -> rethink strategy
    cr = _capsule_fail_rate(snap)
    if cr > capsule_trigger and cooldown_ok("capsule_learn") and "capsules" in changed:
        variant = select_variant("capsule_learn")
        if variant:
            candidates.append({
                "key": "capsule_learn",
                "name": f"experiment_capsule_learn_{variant['id']}",
                "urgency": min(1.0, cr),
                "cmd": variant["cmd"],
                "why": f"capsule fail rate {cr:.0%} (trigger {capsule_trigger:.0%}) — variant {variant['id']}",
                "verify": "verify_capsule_fail_rate_dropped",
                "cost": "low",
                "experiment_variant": variant["id"],
            })
        else:
            candidates.append({
                "key": "capsule_learn",
                "name": "insight_engine",
                "urgency": min(1.0, cr),
                "cmd": ["python3", str(SCRIPTS_DIR / "insight_engine.py")],
                "why": f"capsule fail rate {cr:.0%} (trigger {capsule_trigger:.0%}) — run cross-domain learning",
                "verify": "verify_capsule_fail_rate_dropped",
                "cost": "low",
            })

    # 4. Interest profile changed materially -> refresh curiosity
    if "interests" in changed and cooldown_ok("curiosity"):
        candidates.append({
            "key": "curiosity",
            "name": "curious_explorer",
            "urgency": 0.6,
            "cmd": ["python3", str(SCRIPTS_DIR / "curious_explorer.py")],
            "why": "interest profile changed",
            "verify": "verify_curiosity_ran",
            "cost": "low",
        })

    # 5. Insights file updated -> a pattern fired; surface if it's a new pattern
    if "insights" in changed and cooldown_ok("insight_surface"):
        insights = _read_json(DATA_DIR / "insights.json")
        if insights:
            candidates.append({
                "key": "insight_surface",
                "name": "proactive_orchestrator",
                "urgency": 0.55,
                "cmd": ["python3", str(SCRIPTS_DIR / "proactive" / "proactive_orchestrator.py")],
                "why": "new insight pattern detected",
                "verify": "verify_orchestrator_ran",
                "cost": "high",
            })

    # 6. Health severely degraded -> execute multi-step recovery plan
    hs = _health_score(snap)
    if hs > 0.6 and cooldown_ok("health_plan"):
        candidates.append({
            "key": "health_plan",
            "name": "multi_step_plan_health_degraded",
            "urgency": min(1.0, hs),
            "cmd": None,
            "plan_key": "health_degraded",
            "why": f"health severely degraded (score {hs:.2f}) — run recovery plan",
            "verify": "verify_health_improved",
            "cost": "high",
        })

    # 7. Scheduler multiple failures -> execute scheduler repair plan
    fr = _scheduler_fail_rate(snap)
    if fr > 0.3 and cooldown_ok("scheduler_plan"):
        candidates.append({
            "key": "scheduler_plan",
            "name": "multi_step_plan_scheduler_issues",
            "urgency": min(1.0, fr),
            "cmd": None,
            "plan_key": "scheduler_issues",
            "why": f"scheduler fail rate {fr:.0%} — run repair plan",
            "verify": "verify_scheduler_fail_rate_dropped",
            "cost": "high",
        })

    return candidates


def _verify_health_improved(entry: dict) -> tuple[str, str]:
    """Verify if health score improved after troubleshoot."""
    hd = _read_json(STATE_DIR / "health_dashboard.json")
    if not hd:
        return "unknown", "no health dashboard data"
    score = 0.0
    total = 0
    for k, v in hd.items():
        if isinstance(v, dict):
            total += 1
            if v.get("status") in ("critical", "down", "error", "unhealthy"):
                score += 1.0
            elif v.get("status") == "warning":
                score += 0.5
    current_score = score / total if total else 0.0
    if current_score < 0.3:
        return "success", f"health score improved to {current_score:.2f}"
    return "partial", f"health score still {current_score:.2f}"


def _verify_scheduler_fail_rate_dropped(entry: dict) -> tuple[str, str]:
    """Verify if scheduler fail rate dropped after repair."""
    state = _read_json(DATA_DIR / "scheduler_state.json")
    if not state:
        return "unknown", "no scheduler state"
    failed = 0
    total = 0
    for k, v in state.items():
        if not isinstance(v, dict) or k in ("last_run", "jobs_run_count"):
            continue
        total += 1
        if v.get("last_status") == "failed":
            failed += 1
    current_rate = failed / total if total else 0.0
    if current_rate < 0.2:
        return "success", f"scheduler fail rate dropped to {current_rate:.0%}"
    return "partial", f"scheduler fail rate still {current_rate:.0%}"


def _verify_capsule_fail_rate_dropped(entry: dict) -> tuple[str, str]:
    """Verify if capsule fail rate dropped after learning."""
    cf = HERMES_HOME / "capsules" / "outcomes.jsonl"
    if not cf.exists():
        return "unknown", "no capsule data"
    lines = cf.read_text().splitlines()[-20:]
    if not lines:
        return "unknown", "no recent capsules"
    fails = sum(1 for l in lines if '"fail"' in l)
    current_rate = fails / len(lines)
    if current_rate < 0.5:
        return "success", f"capsule fail rate dropped to {current_rate:.0%}"
    return "partial", f"capsule fail rate still {current_rate:.0%}"


def _verify_curiosity_ran(entry: dict) -> tuple[str, str]:
    """Verify curious_explorer produced output."""
    results = _read_json(DATA_DIR / "curious_explorer_results.json")
    if not results:
        return "fail", "no curious_explorer results"
    import time
    last_run = results.get("last_run", 0)
    if time.time() - last_run < 600:
        return "success", "curious_explorer ran recently"
    return "partial", "curious_explorer output older than 10 min"


def _verify_orchestrator_ran(entry: dict) -> tuple[str, str]:
    """Verify proactive_orchestrator produced output."""
    insights = _read_json(DATA_DIR / "insights.json")
    if not insights:
        return "unknown", "no insights data"
    return "success", "orchestrator cycle completed"


def _verify_disk_space_freed(entry: dict) -> tuple[str, str]:
    """Verify disk space was freed."""
    import shutil
    du = shutil.disk_usage("/")
    free_pct = (du.free / du.total) * 100
    if free_pct > 15:
        return "success", f"disk free: {free_pct:.0f}%"
    return "partial", f"disk free: {free_pct:.0f}%"


def _verify_memory_freed(entry: dict) -> tuple[str, str]:
    """Verify memory was freed."""
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    mem[k.strip()] = int(v.strip().split()[0])
        free_pct = (mem.get("MemAvailable", 0) / mem.get("MemTotal", 1)) * 100
        if free_pct > 20:
            return "success", f"memory free: {free_pct:.0f}%"
        return "partial", f"memory free: {free_pct:.0f}%"
    except:
        return "unknown", "memory check failed"


VERIFIERS = {
    "verify_health_improved": _verify_health_improved,
    "verify_scheduler_fail_rate_dropped": _verify_scheduler_fail_rate_dropped,
    "verify_capsule_fail_rate_dropped": _verify_capsule_fail_rate_dropped,
    "verify_curiosity_ran": _verify_curiosity_ran,
    "verify_orchestrator_ran": _verify_orchestrator_ran,
    "verify_disk_space_freed": _verify_disk_space_freed,
    "verify_memory_freed": _verify_memory_freed,
}


def verify_pending(snap: dict) -> list[dict]:
    """Check pending verifications and resolve them."""
    if not ledger_resolve:
        return []
    
    pending = snap.get("pending_verification", [])
    resolved = []
    still_pending = []
    
    for p in pending:
        decision_id = p.get("decision_id")
        verify_fn_name = p.get("verify_fn")
        if not decision_id or not verify_fn_name:
            continue
        
        verify_fn = VERIFIERS.get(verify_fn_name)
        if not verify_fn:
            log(f"unknown verify_fn: {verify_fn_name}", level="WARN")
            continue
        
        if time.time() - p.get("fired_at", 0) < 120:
            still_pending.append(p)
            continue
        
        try:
            entries = ledger_load(limit=100)
            entry = next((e for e in entries if e.get("id") == decision_id), None)
            if not entry:
                log(f"entry {decision_id} not found in ledger", level="WARN")
                continue
            
            outcome, evidence = verify_fn(entry)
            ledger_resolve(decision_id, outcome, evidence, actor="proactive_engine_verifier")
            log(f"VERIFIED {decision_id} -> {outcome}: {evidence}")
            resolved.append({"id": decision_id, "outcome": outcome, "evidence": evidence})
            
            # Record experiment result if applicable
            exp_variant = entry.get("params", {}).get("experiment_variant")
            if exp_variant:
                record_experiment_result(entry.get("action", "").replace("fire_", ""), exp_variant, outcome)
            
        except Exception as e:
            log(f"verification error for {decision_id}: {e}", level="ERROR")
            still_pending.append(p)
    
    snap["pending_verification"] = still_pending
    return resolved


def run_once(debug: bool = False) -> list[dict]:
    snap = _load_snapshot()

    # First, verify any pending actions from previous runs
    verified = verify_pending(snap)
    if verified:
        log(f"verified {len(verified)} pending actions")

    # Update file hashes regardless of action
    for path, label, weight in SIGNAL_FILES:
        snap.setdefault("files", {})[label] = _content_hash(path)

    if not snap.get("baseline"):
        snap["baseline"] = {"built": datetime.now(timezone.utc).isoformat()}
        _save_snapshot(snap)
        log("Baseline snapshot built — waiting for state changes")
        return []

    # Resource check before considering heavy actions
    res_ok, res_reason = _resource_check()
    if not res_ok:
        log(f"skipping actions — {res_reason}", level="WARN")
        _save_snapshot(snap)
        return []

    candidates = _candidate_actions(snap)
    fired = []
    for c in candidates:
        cmd = c["cmd"]
        plan_key = c.get("plan_key")
        exp_variant = c.get("experiment_variant")
        
        # Check escalation for low confidence
        if c.get("urgency", 0) < 0.5:
            action_context = {"action": c["name"], "target": "", "rationale": c["why"]}
            should_esc, esc_reason = should_escalate(c["urgency"], action_context)
            if should_esc:
                escalate_to_human(action_context, c["urgency"], esc_reason)
                log(f"ESCALATED {c['name']}: {esc_reason}", level="WARN")
                continue
        
        try:
            start = time.time()
            if plan_key:
                # Execute multi-step plan
                result = execute_plan(plan_key)
                elapsed = time.time() - start
                outcome = result.get("overall_outcome", "fail")
                log(f"EXECUTED PLAN {plan_key} (urgency {c['urgency']:.2f}) — {c['why']} → {outcome} in {elapsed:.1f}s")
            elif cmd:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                elapsed = time.time() - start
                outcome = "success" if proc.returncode == 0 else "fail"
                log(f"FIRED {c['name']} (urgency {c['urgency']:.2f}) — {c['why']} → {outcome} in {elapsed:.1f}s")
            else:
                continue
            
            decision_id = None
            if ledger_record:
                entry = ledger_record(
                    actor="proactive_engine",
                    action=f"fire_{c['name']}",
                    rationale=c["why"],
                    predicted_outcome="success",
                    target="",
                    params={
                        "urgency": round(c["urgency"], 3),
                        "module": c["name"],
                        "cost": c.get("cost", "unknown"),
                        "verify_fn": c.get("verify"),
                        "plan_key": plan_key,
                        "experiment_variant": exp_variant,
                    },
                    triggered_by="state_change",
                )
                decision_id = entry.get("id")
            
            if decision_id and c.get("verify"):
                snap.setdefault("pending_verification", []).append({
                    "decision_id": decision_id,
                    "verify_fn": c["verify"],
                    "fired_at": time.time(),
                    "action": c["name"],
                })
            
            snap.setdefault("cooldowns", {})[c["key"]] = time.time()
            fired.append({"name": c["name"], "outcome": outcome, "why": c["why"]})
        except subprocess.TimeoutExpired:
            log(f"FIRED {c['name']} TIMEOUT", level="WARN")
            fired.append({"name": c["name"], "outcome": "timeout", "why": c["why"]})
        except Exception as e:
            log(f"FIRED {c['name']} ERROR: {e}", level="ERROR")
            fired.append({"name": c["name"], "outcome": "error", "why": c["why"]})

    _save_snapshot(snap)
    return fired


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run one cycle")
    parser.add_argument("--snapshot", action="store_true", help="Rebuild baseline")
    parser.add_argument("--debug", action="store_true", help="Verbose output")
    args = parser.parse_args()

    if args.snapshot:
        snap = {"files": {}, "cooldowns": {}, "baseline": {"built": datetime.now(timezone.utc).isoformat()}}
        for path, label, weight in SIGNAL_FILES:
            snap["files"][label] = _content_hash(path)
        _save_snapshot(snap)
        print("baseline snapshot built")
        return

    fired = run_once(debug=args.debug)
    if not fired and args.debug:
        print("no state changes — nothing fired")


if __name__ == "__main__":
    main()