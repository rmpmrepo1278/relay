#!/usr/bin/env python3
"""state_verdict.py — the "Board of Directors" monthly audit of you and your system.

Each of the 5 council members evaluates one dimension of the last month and
renders a numbered score (0-100) plus a one-line verdict:
  * learning_integrator : goals (goal_engine) — momentum, completion
  * insight_engine      : cross-domain connections (memory synthesizer insights)
  * adversarial_engine  : risk & safety (recent failures, escalations)
  * predictive_signals  : trends (is the system getting better or worse?)
  * self_correction     : fix-rate (did corrections stick / regressions)

The board's score = mean of the 5 member scores. Its single biggest
correction for next month is the lowest-scoring dimension's suggestion.

Output:
  * stores a BOARD verdict row in decision_register (source=monthly_verdict)
  * writes state/verdict_YYYY-MM.md (the report)
  * pages a compact verdict to Telegram (deduped, so at most once/month)

CLI:
  python3 state_verdict.py            # run (with 28-day dedup window)
  python3 state_verdict.py --force    # run regardless of window
  python3 state_verdict.py --dry-run  # compute + print, don't persist/page
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from experience_builds import (
    HERMES_HOME, DATA, page_telegram, within_window, mark_run, read_json,
    get_db, insert_decision, recent_failures, recent_outcomes, _now,
)

MEMBERS = ["learning_integrator", "insight_engine", "adversarial_engine",
           "predictive_signals", "self_correction"]
WINDOW_HOURS_STATE = "verdict_window"
DEDUP_HOURS = int(os.environ.get("VERDICT_DEDUP_HOURS", "672"))  # ~28 days, monthly


# ──────────────────────────────────────
# Dimension readers (defensive, never raise)
# ──────────────────────────────────────
def _goal_evidence() -> dict:
    """learning_integrator: goal momentum from goal_engine.db."""
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import goal_engine as ge
        stats = ge.get_goal_stats()
        active = ge.get_active_goals()
        total = stats.get("active", 0) + stats.get("completed", 0)
        completion = (stats.get("completed", 0) / total) if total else 0.0
        avg_progress = stats.get("avg_progress", 0.0)
        return {"active": stats.get("active", 0), "completed": stats.get("completed", 0),
                "completion_rate": round(completion * 100),
                "avg_progress": round(avg_progress * 100),
                "goals": [g.get("title", "?")[:40] for g in (active or [])[:5]]}
    except Exception as e:
        return {"error": str(e)}


def _insight_evidence() -> dict:
    """insight_engine: how many cross-domain insights surfaced this month."""
    try:
        insights_file = DATA / "insights.json"
        data = read_json(insights_file, [])
        if not isinstance(data, list):
            data = []
        return {"insights": len(data),
                "samples": [i.get("content", "")[:80] for i in data[:3]]}
    except Exception as e:
        return {"error": str(e)}


def _risk_evidence() -> dict:
    """adversarial_engine: service risk from recent failures + escalations."""
    fails = recent_failures(hours=30 * 24)
    outcomes = recent_outcomes(hours=30 * 24)
    max_blast = 0
    for o in outcomes:
        try:
            blast = json.loads(o.get("blast_radius") or "{}")
        except Exception:
            blast = {}
        max_blast = max(max_blast, int(blast.get("services", 0) or 0))
    return {"recent_failures_30d": fails, "max_blast_radius": max_blast}


def _trend_evidence() -> dict:
    """predictive_signals: is the failure rate improving or worsening?"""
    this_week = recent_failures(hours=7 * 24)
    prev_weeks = recent_failures(hours=30 * 24) - this_week
    slope = (this_week - prev_weeks) / max(prev_weeks, 1)
    return {"last7d": this_week, "prev_weeks_23d": prev_weeks, "delta_pct": round(slope * 100)}


def _fix_evidence() -> dict:
    """self_correction: did corrections stick? uses outcomes success/fail."""
    try:
        c = get_db()
        rows = c.execute(
            "SELECT outcome, COUNT(*) FROM outcomes WHERE timestamp > ? GROUP BY outcome",
            ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),),
        ).fetchall()
        c.close()
        d = {r[0]: r[1] for r in rows}
        total = sum(d.values())
        fix_rate = (d.get("success", 0) / total * 100) if total else 100.0
        return {"success": d.get("success", 0), "fail": d.get("fail", 0),
                "fix_rate_pct": round(fix_rate)}
    except Exception as e:
        return {"error": str(e)}


# ──────────────────────────────────────
# Per-member scoring (deterministic, evidence-based)
# ──────────────────────────────────────
def member_score(member: str, ev: dict) -> tuple[int, str]:
    if member == "learning_integrator":
        comp = ev.get("completion_rate", 0)
        prog = ev.get("avg_progress", 0)
        score = min(100, int(0.6 * comp + 0.4 * prog + len(ev.get("goals", [])) * 2))
        return score, f"goals: {ev.get('active',0)} active, {ev.get('completed',0)} done ({comp}% complete)"
    if member == "insight_engine":
        n = ev.get("insights", 0)
        score = min(100, 40 + n * 8)
        return score, f"{n} cross-domain insights this month"
    if member == "adversarial_engine":
        fails = ev.get("recent_failures_30d", 0)
        score = max(0, 100 - fails * 6 - ev.get("max_blast_radius", 0) * 10)
        return score, f"risk: {fails} failures in 30d, max blast {ev.get('max_blast_radius',0)}"
    if member == "predictive_signals":
        delta = ev.get("delta_pct", 0)
        score = min(100, max(0, 100 + delta))
        return score, f"failure trend: {'worsening' if delta>10 else 'stable' if delta>-10 else 'improving'} ({delta:+}%)"
    if member == "self_correction":
        rate = ev.get("fix_rate_pct", 100)
        return rate, f"correction fix-rate {rate}%"
    return 50, "no evidence"


# ──────────────────────────────────────
# Main
# ──────────────────────────────────────
def run_verdict(force: bool = False, dry: bool = False) -> dict:
    if not force and not dry and within_window(WINDOW_HOURS_STATE, DEDUP_HOURS):
        return {"skipped": "within dedup window", "next": DEDUP_HOURS}

    evidences = {
        "learning_integrator": _goal_evidence(),
        "insight_engine": _insight_evidence(),
        "adversarial_engine": _risk_evidence(),
        "predictive_signals": _trend_evidence(),
        "self_correction": _fix_evidence(),
    }
    verdicts = {}
    for m in MEMBERS:
        score, note = member_score(m, evidences[m])
        verdicts[m] = {"score": score, "note": note}

    overall = round(sum(v["score"] for v in verdicts.values()) / len(MEMBERS))
    worst = min(MEMBERS, key=lambda m: verdicts[m]["score"])
    correction = {
        "learning_integrator": "Re-engage the top inactive goal; break it into one next action this week.",
        "insight_engine": "Pull 3 cross-domain insights into one concrete weekly experiment.",
        "adversarial_engine": "Auto-remediate the most repeated failure class before it bites again.",
        "predictive_signals": "Schedule capacity work ahead of the trend that is degrading fastest.",
        "self_correction": "Verify the last N corrections actually resolved; retire the ones that didn't.",
    }[worst]

    report = {
        "generated_at": _now(),
        "overall": overall,
        "members": verdicts,
        "worst_dimension": worst,
        "top_correction": correction,
        "evidences": {m: ev for m, ev in evidences.items()},
    }

    if dry:
        return report

    # persist: state mark + markdown report + decision_register board row
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    md = [
        f"# State of the System — {month}", "",
        f"**Overall score: {overall}/100**",
        f"**Biggest correction (from {worst}):** {correction}", "",
        "## Board votes", "",
    ]
    for m in MEMBERS:
        v = verdicts[m]
        md.append(f"- **{m}**: {v['score']}/100 — {v['note']}")
    md.append(f"\n_Generated {report['generated_at']}_")
    doc = Path(DATA) / "state_verdicts"
    doc.mkdir(parents=True, exist_ok=True)
    (doc / f"verdict_{month}.md").write_text("\n".join(md))
    (doc / f"verdict_{month}.json").write_text(json.dumps(report, indent=2))

    db = get_db()
    insert_decision(db, summary=f"State-of-System verdict {month}: {overall}/100",
                    context=f"worst={worst}; correction={correction}",
                    source="monthly_verdict", status="completed",
                    domain="self_review")
    db.close()

    # Human-in-the-loop: the board's top correction becomes a consent ballot.
    # Personal-domain corrections require your 6th vote before they enqueue as
    # a tracked commitment; infra corrections go out with a [trial] tag.
    routed = None
    if os.environ.get("EXPERIENCE_ROUTE_CORRECTIONS", "1") == "1":
        try:
            sys.path.insert(0, str(HERMES_HOME / "scripts"))
            import human_overrides as _gov
            routed = _gov.route_correction(correction, source="monthly_verdict")
        except Exception as e:
            routed = {"error": str(e)}

    mark_run(WINDOW_HOURS_STATE, overall=overall, worst=worst, month=month)

    tg = (f"🗳️ **State of the System — {month}**\n"
          f"Overall: **{overall}/100**\n"
          f"Most-lagging dimension: *{worst}*\n"
          f"📌 Next correction: {correction}")
    page = page_telegram(tg)
    report["telegram"] = page
    report["correction_routed"] = bool(routed and routed.get("gate"))
    return report


def main(argv):
    force = "--force" in argv
    dry = "--dry-run" in argv
    r = run_verdict(force=force, dry=dry)
    print(json.dumps(r, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))