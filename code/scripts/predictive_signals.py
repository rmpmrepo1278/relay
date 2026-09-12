#!/usr/bin/env python3
"""
predictive_signals.py — Trend analysis for preemptive action.

Analyzes historical data to predict future issues:
- Disk space exhaustion timeline
- Memory leak trends
- Error rate acceleration
- Backup aging
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
DATA_DIR = HERMES_HOME / "data"
STATE_DIR = HERMES_HOME / "state"
TRENDS_FILE = DATA_DIR / "predictive_trends.json"
HISTORY_DIR = DATA_DIR / "signal_history"

sys.path.insert(0, str(HERMES_HOME / "scripts"))
try:
    from decision_ledger import load as ledger_load
except ImportError:
    def ledger_load(limit=0, status=""):
        return []


def _ensure_history_dir():
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def record_signal(signal_name: str, value: float, timestamp: str = None):
    """Record a signal value for trend analysis."""
    _ensure_history_dir()
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    history_file = HISTORY_DIR / f"{signal_name}.jsonl"
    entry = {"timestamp": ts, "value": value}
    with open(history_file, "a") as f:
        f.write(json.dumps(entry) + "\n")
    # Keep last 1000 points
    lines = history_file.read_text().splitlines()
    if len(lines) > 1000:
        with open(history_file, "w") as f:
            f.write("\n".join(lines[-1000:]) + "\n")


def get_signal_history(signal_name: str, hours: int = 24) -> list[tuple[datetime, float]]:
    """Get signal history for the last N hours."""
    history_file = HISTORY_DIR / f"{signal_name}.jsonl"
    if not history_file.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    points = []
    for line in history_file.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            ts = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
            if ts >= cutoff:
                points.append((ts, e["value"]))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return sorted(points)


def compute_trend(points: list[tuple[datetime, float]]) -> dict:
    """Compute linear trend (slope per hour) and R²."""
    if len(points) < 3:
        return {"slope_per_hour": 0.0, "r2": 0.0, "points": len(points)}
    
    # Convert to hours since first point
    t0 = points[0][0].timestamp()
    xs = [(p[0].timestamp() - t0) / 3600 for p in points]
    ys = [p[1] for p in points]
    
    n = len(points)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)
    sum_y2 = sum(y * y for y in ys)
    
    if n * sum_x2 == sum_x * sum_x:
        return {"slope_per_hour": 0.0, "r2": 0.0, "points": n}
    
    slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
    intercept = (sum_y - slope * sum_x) / n
    
    # R²
    ss_tot = sum((y - sum_y/n)**2 for y in ys)
    ss_res = sum((y - (slope * x + intercept))**2 for x, y in zip(xs, ys))
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    
    return {"slope_per_hour": slope, "intercept": intercept, "r2": r2, "points": n}


def predict_time_to_threshold(current_value: float, slope_per_hour: float, threshold: float, direction: str = "increasing") -> float | None:
    """Predict hours until value crosses threshold. Returns None if never or wrong direction."""
    if slope_per_hour == 0:
        return None
    
    if direction == "increasing" and slope_per_hour <= 0:
        return None
    if direction == "decreasing" and slope_per_hour >= 0:
        return None
    
    hours = (threshold - current_value) / slope_per_hour
    return hours if hours > 0 else None


def analyze_all_signals() -> dict:
    """Analyze all tracked signals for predictions."""
    signals_to_track = {
        "disk_usage_pct": {"threshold": 90, "direction": "increasing", "unit": "%"},
        "memory_usage_pct": {"threshold": 90, "direction": "increasing", "unit": "%"},
        "health_score": {"threshold": 0.7, "direction": "increasing", "unit": "score"},
        "scheduler_fail_rate": {"threshold": 0.3, "direction": "increasing", "unit": "rate"},
        "capsule_fail_rate": {"threshold": 0.6, "direction": "increasing", "unit": "rate"},
        "mcp_health_score": {"threshold": 0.7, "direction": "increasing", "unit": "score"},
    }
    
    predictions = {}
    for signal_name, config in signals_to_track.items():
        points = get_signal_history(signal_name, hours=72)  # 3 days
        if len(points) < 5:
            continue
        
        trend = compute_trend(points)
        current = points[-1][1]
        slope = trend["slope_per_hour"]
        r2 = trend["r2"]
        
        if r2 < 0.1:  # Weak trend
            continue
        
        hours_to_threshold = predict_time_to_threshold(
            current, slope, config["threshold"], config["direction"]
        )
        
        if hours_to_threshold is not None and hours_to_threshold < 168:  # within a week
            predictions[signal_name] = {
                "current_value": round(current, 3),
                "slope_per_hour": round(slope, 6),
                "r2": round(r2, 3),
                "threshold": config["threshold"],
                "predicted_hours_to_threshold": round(hours_to_threshold, 1),
                "predicted_time": (datetime.now(timezone.utc) + timedelta(hours=hours_to_threshold)).isoformat(),
                "severity": "critical" if hours_to_threshold < 24 else "warning" if hours_to_threshold < 72 else "info",
                "unit": config["unit"],
            }
    
    # Save trends
    trends_data = {
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "predictions": predictions,
        "trends": {k: compute_trend(get_signal_history(k, 72)) for k in signals_to_track.keys()},
    }
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TRENDS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(trends_data, indent=2, default=str))
    os.replace(tmp, TRENDS_FILE)
    
    return trends_data


def get_predictions() -> dict:
    """Get current predictions."""
    if TRENDS_FILE.exists():
        try:
            return json.loads(TRENDS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"predictions": {}}


def collect_current_signals() -> dict:
    """Collect current signal values from system + MCP server health."""
    import shutil
    import urllib.request
    signals = {}
    


    # Disk usage
    du = shutil.disk_usage("/")
    signals["disk_usage_pct"] = round((du.used / du.total) * 100, 2)
    
    # Memory usage
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    mem[k.strip()] = int(v.strip().split()[0])
        mem_used_pct = ((mem.get("MemTotal", 1) - mem.get("MemAvailable", 0)) / mem.get("MemTotal", 1)) * 100
        signals["memory_usage_pct"] = round(mem_used_pct, 2)
    except:
        pass
    
    # Health score
    import json as _json
    hd = STATE_DIR / "health_dashboard.json"
    if hd.exists():
        try:
            data = _json.loads(hd.read_text())
            score = 0.0
            total = 0
            for k, v in data.items():
                if isinstance(v, dict):
                    total += 1
                    if v.get("status") in ("critical", "down", "error", "unhealthy"):
                        score += 1.0
                    elif v.get("status") == "warning":
                        score += 0.5
            if total:
                signals["health_score"] = round(score / total, 3)
        except:
            pass
    
    # Scheduler fail rate
    sd = DATA_DIR / "scheduler_state.json"
    if sd.exists():
        try:
            data = _json.loads(sd.read_text())
            failed = 0
            total = 0
            for k, v in data.items():
                if not isinstance(v, dict) or k in ("last_run", "jobs_run_count"):
                    continue
                total += 1
                if v.get("last_status") == "failed":
                    failed += 1
            if total:
                signals["scheduler_fail_rate"] = round(failed / total, 3)
        except:
            pass
    
    # Capsule fail rate
    cf = HERMES_HOME / "capsules" / "outcomes.jsonl"
    if cf.exists():
        try:
            lines = cf.read_text().splitlines()[-40:]
            if lines:
                fails = sum(1 for l in lines if '"fail"' in l)
                signals["capsule_fail_rate"] = round(fails / len(lines), 3)
        except:
            pass

    # --- MCP server health ---
    # Check MCP servers registered in config
    try:
        import yaml
        cfg_path = HH / "config.yaml"
        if cfg_path.exists():
            cfg = yaml.safe_load(cfg_path.read_text())
            mcp_servers = cfg.get("mcp_servers", {})
            unhealthy_mcp = 0
            total_mcp = 0
            for name, scfg in mcp_servers.items():
                if not scfg.get("enabled", True):
                    continue
                total_mcp += 1
                # MCP servers are checked via their health if exposed
                # For stdio MCP servers, check process presence
                cmd = scfg.get("command", "")
                if cmd and "uvicorn" in cmd or "python" in cmd:
                    # Check if MCP process is running
                    r = subprocess.run(
                        ["pgrep", "-f", str(scfg.get("args", [""])[0])],
                        capture_output=True, text=True, timeout=5,
                    )
                    if r.returncode != 0:
                        unhealthy_mcp += 1
            if total_mcp > 0:
                signals["mcp_health_score"] = round(1.0 - (unhealthy_mcp / total_mcp), 3)
    except Exception:
        pass

    # --- Internet outage window awareness ---
    # Daily internet outage ~11PM-9AM PT
    try:
        from datetime import datetime as _dt
        now_pt = _dt.now(__import__('pytz').timezone('US/Pacific')) if __import__('importlib.util', fromlist=['find_spec']).find_spec('pytz') else _dt.now()
        hour = now_pt.hour
        # Outage window: 23:00-09:00 PT
        signals["internet_outage_window"] = 1.0 if (hour >= 23 or hour < 9) else 0.0
        signals["internet_outage_window_active"] = 1.0 if (hour >= 23 or hour < 9) else 0.0
    except Exception:
        pass

    return signals


def record_current_signals():
    """Collect and record all current signals."""
    signals = collect_current_signals()
    for name, value in signals.items():
        record_signal(name, value)
    return signals


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--collect", action="store_true", help="Collect and record current signals")
    parser.add_argument("--analyze", action="store_true", help="Analyze trends and generate predictions")
    parser.add_argument("--show", action="store_true", help="Show current predictions")
    parser.add_argument("--history", help="Show history for signal")
    args = parser.parse_args()
    
    if args.collect:
        signals = record_current_signals()
        print(f"Recorded: {signals}")
    elif args.analyze:
        result = analyze_all_signals()
        print(json.dumps(result, indent=2, default=str))
    elif args.show:
        preds = get_predictions()
        print(json.dumps(preds, indent=2, default=str))
    elif args.history:
        points = get_signal_history(args.history, 168)
        print(json.dumps([{"time": p[0].isoformat(), "value": p[1]} for p in points], indent=2))
    else:
        # Default: collect then analyze
        record_current_signals()
        result = analyze_all_signals()
        preds = result.get("predictions", {})
        if preds:
            print("PREDICTIONS:")
            for k, v in preds.items():
                print(f"  {k}: {v['current_value']}{v['unit']} -> threshold {v['threshold']} in {v['predicted_hours_to_threshold']}h ({v['severity']})")
        else:
            print("No predictions (insufficient data or no trends crossing thresholds)")


if __name__ == "__main__":
    # ── Agent Parliament: council vote (pre-main dispatch) ──────────
    if '--vote-council' in __import__('sys').argv or '--vote' in __import__('sys').argv:
        _os = __import__('os')
        _sys = __import__('sys')
        _dir = _os.path.dirname(_os.path.abspath(__file__))
        _sys.path.insert(0, _os.path.join(_dir, 'lib'))
        try:
            from council_vote import cast_vote as _council_cast
        except Exception:
            _sys.path.insert(0, '/home/rohit/.hermes/hermes-agent/scripts/lib')
            from council_vote import cast_vote as _council_cast
        _dry = '--dry-run' in _sys.argv
        _res = _council_cast('predictive_signals', dry=_dry)
        if _dry:
            print('[predictive_signals would-cast: ' + '; '.join(f"{_p}={_v}" for _p, _v in _res) or f'[predictive_signals] no open proposals')
        else:
            print(f'[predictive_signals] cast ' + '; '.join(f"{_p}={_v}" for _p, _v in _res) or f'[predictive_signals] no votes needed')
        _sys.exit(0)

    main()