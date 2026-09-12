#!/usr/bin/env python3
"""learning_integrator.py - analyze session patterns and suggest improvements."""
import json
from pathlib import Path
from collections import Counter
from datetime import datetime

HERMES_HOME = Path.home() / ".hermes"
LOGS_DIR = HERMES_HOME / "logs"

def analyze_session_patterns():
    """Find common failure patterns in logs."""
    patterns = Counter()
    
    for log in LOGS_DIR.glob("*.log"):
        try:
            lines = log.read_text().split("\n")
            for line in lines[-100:]:
                if "fail" in line.lower() or "error" in line.lower():
                    patterns[line[:100]] += 1
        except:
            pass
    
    return patterns.most_common(20)

def suggest_improvements(patterns):
    """Generate improvement suggestions for SOUL.md."""
    suggestions = []
    for pattern, count in patterns:
        if count > 3:
            suggestions.append(f"- Pattern: {pattern} occurred {count} times - add lazy-dev skip")
    return suggestions

def main():
    patterns = analyze_session_patterns()
    improvements = suggest_improvements(patterns)
    
    log = HERMES_HOME / "logs" / "learning_insights.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    
    with open(log, "a") as f:
        f.write(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "patterns": patterns,
            "suggestions": improvements[:10]
        }) + "\n")
    
    for s in improvements[:5]:
        print(s)

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
        _res = _council_cast('learning_integrator', dry=_dry)
        if _dry:
            print('[learning_integrator would-cast: ' + '; '.join(f"{_p}={_v}" for _p, _v in _res) or f'[learning_integrator] no open proposals')
        else:
            print(f'[learning_integrator] cast ' + '; '.join(f"{_p}={_v}" for _p, _v in _res) or f'[learning_integrator] no votes needed')
        _sys.exit(0)

    main()