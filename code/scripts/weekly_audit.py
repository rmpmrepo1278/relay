#!/usr/bin/env python3
"""weekly_audit.py — Hermes self-review of decision effectiveness."""
import json, sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import Counter

HERMES_HOME = Path.home() / ".hermes"
DB_PATH = HERMES_HOME / "state" / "hermes_memory.db"
DECISIONS_LOG = HERMES_HOME / "logs" / "autonomous_decisions.jsonl"
AUDIT_FILE = HERMES_HOME / "logs" / "weekly_audit.jsonl"
SOUL_FILE = HERMES_HOME / "SOUL.md"

def analyze_effectiveness():
    """Analyze which actions work and which don't."""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute(
        "SELECT gene, outcome, count, success_count, failure_streak, tier FROM actions ORDER BY count DESC"
    )
    rows = cur.fetchall()
    conn.close()

    stats = []
    for gene, outcome, cnt, succ, streak, tier in rows:
        rate = round(succ / cnt * 100, 1) if cnt > 0 else 0
        stats.append({
            "gene": gene, "total": cnt, "successes": succ,
            "failures": cnt - succ, "rate": rate,
            "streak": streak, "tier": tier,
            "recommendation": "keep" if rate > 70 else ("adjust" if rate > 30 else "remove")
        })

    # Genes to disable (low effectiveness)
    to_disable = [s["gene"] for s in stats if s["recommendation"] == "remove"]
    to_adjust = [s["gene"] for s in stats if s["recommendation"] == "adjust"]

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "period": "7d",
        "total_genes": len(stats),
        "avg_success_rate": round(sum(s["rate"] for s in stats) / len(stats), 1) if stats else 0,
        "recommendations": {
            "disable": to_disable,
            "adjust_threshold": to_adjust
        },
        "stats": stats
    }

    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_FILE, "a") as f:
        f.write(json.dumps(report) + "\n")

    # Write to SOUL.md  
    if to_disable:
        existing = SOUL_FILE.read_text() if SOUL_FILE.exists() else "# Hermes SOUL\n"
        for gene in to_disable:
            entry = f"\n# Auto-disabled: {gene}\n- **Reason**: < 30% success rate in self-audit\n- **Action**: Consider removing or replacing\n"
            if f"Auto-disabled: {gene}" not in existing:
                SOUL_FILE.write_text(SOUL_FILE.read_text() + entry)

    return report

if __name__ == "__main__":
    r = analyze_effectiveness()
    print(json.dumps({k: v for k, v in r.items() if k != "stats"}, indent=2))
    print(f"\nEffectiveness: {r['avg_success_rate']}% across {r['total_genes']} genes")
    print(f"Disable recommendation: {r['recommendations']['disable']}")
