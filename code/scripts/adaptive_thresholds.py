#!/usr/bin/env python3
"""
adaptive_thresholds.py — Learn optimal thresholds from decision ledger history.

Analyzes past actions and their verified outcomes to adapt:
- Health score trigger threshold
- Scheduler fail rate trigger threshold  
- Capsule fail rate trigger threshold
- Cooldown periods per action type
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
DATA_DIR = HERMES_HOME / "data"
STATE_DIR = HERMES_HOME / "state"
THRESHOLDS_FILE = DATA_DIR / "adaptive_thresholds.json"
LEDGER_FILE = DATA_DIR / "decision_ledger.jsonl"

sys.path.insert(0, str(HERMES_HOME / "scripts"))
try:
    from decision_ledger import load as ledger_load
except ImportError:
    def ledger_load(limit=0, status=""):
        if not LEDGER_FILE.exists():
            return []
        entries = []
        for line in LEDGER_FILE.read_text().splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if status and e.get("status") != status:
                continue
            entries.append(e)
        if limit > 0:
            entries = entries[-limit:]
        return entries


# Default thresholds (will be adapted over time)
DEFAULTS = {
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
    "min_verification_delay_sec": 120,
}


def _load_thresholds() -> dict:
    if THRESHOLDS_FILE.exists():
        try:
            data = json.loads(THRESHOLDS_FILE.read_text())
            # Merge with defaults for any missing keys
            for k, v in DEFAULTS.items():
                if k not in data:
                    data[k] = v
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULTS.copy()


def _save_thresholds(thresholds: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = THRESHOLDS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(thresholds, indent=2))
    os.replace(tmp, THRESHOLDS_FILE)


def analyze_outcomes() -> dict:
    """Analyze resolved ledger entries to learn what thresholds work."""
    entries = ledger_load(limit=1000, status="resolved")
    if not entries:
        return {"reason": "no resolved entries yet"}
    
    # Group by action type
    by_action = defaultdict(list)
    for e in entries:
        action = e.get("action", "")
        if "fire_" in action:
            by_action[action].append(e)
    
    results = {}
    for action, items in by_action.items():
        successes = [e for e in items if e.get("actual_outcome") == "success"]
        partials = [e for e in items if e.get("actual_outcome") == "partial"]
        fails = [e for e in items if e.get("actual_outcome") == "fail"]
        
        total = len(items)
        success_rate = len(successes) / total if total else 0
        
        # Extract the signal values that triggered this action
        signal_values = []
        for e in items:
            params = e.get("params", {})
            # Different actions have different signal params
            if "health" in action:
                # Health score not directly in params, need to infer from rationale
                pass
        
        results[action] = {
            "total": total,
            "success": len(successes),
            "partial": len(partials),
            "fail": len(fails),
            "success_rate": round(success_rate, 3),
        }
    
    return results


def adapt_thresholds() -> dict:
    """Adapt thresholds based on historical outcomes."""
    thresholds = _load_thresholds()
    analysis = analyze_outcomes()
    
    if "reason" in analysis:
        return {"adapted": False, "reason": analysis["reason"], "current": thresholds}
    
    changes = []
    
    # For each action type, adjust threshold if success rate is poor
    for action, stats in analysis.items():
        if stats["total"] < 5:  # Need enough data
            continue
            
        success_rate = stats["success_rate"]
        
        if "troubleshoot" in action:
            # If troubleshoot rarely succeeds, health trigger may be too sensitive (firing too early)
            # or too insensitive (firing too late). Let's be conservative.
            if success_rate < 0.3:
                # Raise threshold - be more selective
                old = thresholds["health_score_trigger"]
                new = min(0.5, old + 0.05)
                if new != old:
                    thresholds["health_score_trigger"] = round(new, 2)
                    changes.append(f"health_score_trigger: {old} -> {new} (low success {success_rate})")
            elif success_rate > 0.7:
                # Lower threshold - can catch issues earlier
                old = thresholds["health_score_trigger"]
                new = max(0.2, old - 0.05)
                if new != old:
                    thresholds["health_score_trigger"] = round(new, 2)
                    changes.append(f"health_score_trigger: {old} -> {new} (high success {success_rate})")
        
        elif "scheduler_repair" in action:
            if success_rate < 0.3:
                old = thresholds["scheduler_fail_rate_trigger"]
                new = min(0.4, old + 0.05)
                if new != old:
                    thresholds["scheduler_fail_rate_trigger"] = round(new, 2)
                    changes.append(f"scheduler_fail_rate_trigger: {old} -> {new} (low success {success_rate})")
            elif success_rate > 0.7:
                old = thresholds["scheduler_fail_rate_trigger"]
                new = max(0.1, old - 0.05)
                if new != old:
                    thresholds["scheduler_fail_rate_trigger"] = round(new, 2)
                    changes.append(f"scheduler_fail_rate_trigger: {old} -> {new} (high success {success_rate})")
        
        elif "capsule_learn" in action:
            if success_rate < 0.3:
                old = thresholds["capsule_fail_rate_trigger"]
                new = min(0.7, old + 0.05)
                if new != old:
                    thresholds["capsule_fail_rate_trigger"] = round(new, 2)
                    changes.append(f"capsule_fail_rate_trigger: {old} -> {new} (low success {success_rate})")
        
        # Adapt cooldowns based on frequency of firing
        action_key = action.replace("fire_", "")
        if action_key in thresholds["cooldowns_min"]:
            # If we fire often and succeed, can reduce cooldown
            # If we fire often and fail, increase cooldown
            fires_per_day = stats["total"] / max(1, (datetime.now(timezone.utc) - datetime.fromisoformat(
                items[0].get("timestamp", "").replace("Z", "+00:00")) if items else datetime.now(timezone.utc)
            ).days)
            if fires_per_day > 2 and success_rate < 0.4:
                old = thresholds["cooldowns_min"][action_key]
                new = min(120, old * 1.5)
                if new != old:
                    thresholds["cooldowns_min"][action_key] = int(new)
                    changes.append(f"cooldown {action_key}: {old} -> {new} (too frequent, low success)")
            elif fires_per_day < 0.5 and success_rate > 0.6:
                old = thresholds["cooldowns_min"][action_key]
                new = max(5, int(old * 0.8))
                if new != old:
                    thresholds["cooldowns_min"][action_key] = int(new)
                    changes.append(f"cooldown {action_key}: {old} -> {new} (infrequent, high success)")
    
    if changes:
        _save_thresholds(thresholds)
        return {"adapted": True, "changes": changes, "current": thresholds}
    
    return {"adapted": False, "changes": [], "current": thresholds}


def get_thresholds() -> dict:
    """Get current adaptive thresholds (for use by proactive_engine)."""
    return _load_thresholds()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapt", action="store_true", help="Run adaptation now")
    parser.add_argument("--show", action="store_true", help="Show current thresholds")
    args = parser.parse_args()
    
    if args.adapt:
        result = adapt_thresholds()
        print(json.dumps(result, indent=2, default=str))
    elif args.show:
        print(json.dumps(_load_thresholds(), indent=2, default=str))
    else:
        result = adapt_thresholds()
        if result.get("adapted"):
            print(f"Adapted: {result['changes']}")
        else:
            print(f"No adaptation: {result.get('reason', 'insufficient data')}")


if __name__ == "__main__":
    main()