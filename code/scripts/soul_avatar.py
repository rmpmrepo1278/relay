#!/usr/bin/env python3
"""soul_avatar.py — the conscience that talks back to you.

Reads your SOUL_*.md overlays + personal_model life_goals + journals + narrative
themes, then finds a single *contradiction* between what you say you want and
what you actually did, and pages a direct, opinionated challenge.

It does not lecture generically: every challenge is grounded in real data
(a goal from goal_engine, a theme from narrative memory, a journal line).

CLI:
  python3 soul_avatar.py             # run (6h dedup window default)
  python3 soul_avatar.py --force     # bypass dedup window
  python3 soul_avatar.py --dry-run   # print challenge, persist/page nothing
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from experience_builds import (
    HERMES_HOME, DATA, page_telegram, within_window, mark_run, read_json,
    read_text, _now,
)

DEDUP_HOURS = float(os.environ.get("SOUL_DEDUP_HOURS", "6"))
STATE_NAME = "soul_avatar_window"


def _load_goals() -> list[dict]:
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import goal_engine as ge
        return ge.get_active_goals() or []
    except Exception:
        return []


def _load_themes() -> list[str]:
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import narrative_memory as nm
        return [t for t, _ in (nm.top_themes(5) or [])]
    except Exception:
        return []


def _load_overlay(domain: str) -> str:
    f = HERMES_HOME / f"SOUL_{domain.upper()}.md"
    return read_text(f, "")


def _goal_behavior_mismatch(goals: list[dict]) -> list[dict]:
    """Surface active goals that look stalled (low/no progress or old)."""
    out = []
    for g in goals:
        p = g.get("progress") or 0.0
        updated = g.get("updated_at", "")[:10]
        if p < 0.3 and updated:
            out.append({"goal": g.get("title", "?"), "progress": round(p * 100),
                        "last_touched": updated,
                        "kind": "stalled_goal"})
    return out[:2]


def _insight_action_gap() -> dict | None:
    """Fallback evidence: 'you know, but you haven't acted' (insight-action gap)."""
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import narrative_memory as nm
        gap = nm.compute_insight_action_gap()
        if gap and gap.get("gap", 0) > 0:
            return {"total_insights": gap.get("total_insights", 0),
                    "acted": gap.get("acted_insights", 0),
                    "gap": gap.get("gap", 0),
                    "action_rate": gap.get("action_rate", 0),
                    "last_24h": gap.get("last_24h", {})}
    except Exception:
        return None
    return None


PLANNING_STOPWORDS = {
    "plan", "plans", "planning", "task", "tasks", "goal", "goals", "decompose",
    "decomposed", "decomposing", "into", "about", "will", "need", "should",
    "do", "did", "make", "work", "week", "next", "action", "steps", "step",
}


def _planning_bias(themes: list[str]) -> bool:
    """Do you talk MORE about the mechanics of planning than the substance?"""
    if not themes:
        return False
    return all(t in PLANNING_STOPWORDS for t in themes[:3])


def _journal_evidence(mismatches: list[dict]) -> list[str]:
    """Pull 2 journal lines that reference a stalled goal's keywords."""
    lines = []
    jour = HERMES_HOME / "collaborator-memory" / "journal"
    if jour.exists():
        files = sorted(jour.glob("*.md"))[-10:]
        keywords = []
        for m in mismatches:
            for w in (m.get("goal") or "").lower().split()[:3]:
                if len(w) > 3:
                    keywords.append(w)
        for f in files:
            txt = read_text(f, "")
            for line in txt.splitlines():
                low = line.lower()
                if any(k in low for k in keywords) and "http" not in low:
                    lines.append(f"{f.name}: {line.strip()[:140]}")
                    if len(lines) >= 2:
                        break
            if len(lines) >= 2:
                break
    return lines


def compose_challenge() -> dict | None:
    goals = _load_goals()
    themes = _load_themes()
    overlay = _load_overlay("personal")[:300]
    mismatches = _goal_behavior_mismatch(goals)
    journal = _journal_evidence(mismatches)

    # Fallback #1: knowledge-without-action contradiction (insight-action gap)
    gap = _insight_action_gap() if not journal else None

    if not mismatches and not journal and not gap:
        # Fallback #3: your narrative is dominated by planning-mechanics, not substance
        if _planning_bias(themes):
            text = [
                f"\u2694\ufe0f **Soul check-in** — I read your memory and noticed something.",
                "",
                f"Your recurring themes right now are: *{', '.join(themes[:3])}*.",
                "",
                "That's a lot of *process* and almost no *outcome*. Planning, decomposing, "
                "tasking — but your second brain is thin on the substance you care about.",
                "",
                "I'm not accusing. I'm asking: **which one of your goals are you going to "
                "actually land this month — not just plan?** Point me at it and I'll run "
                "the deadline.",
            ]
            return {"challenge": "\n".join(text), "stalled_goal": None,
                    "themes_top": themes[:2], "journal_evidence": [],
                    "evidence_kind": "planning_bias"}
        return None

    theme = ""
    if themes:
        theme = themes[0]

    if journal or mismatches:
        stalled = mismatches[0] if mismatches else {"goal": "your stated focus", "progress": 0}
        text = [
            f"\u2694\ufe0f **Soul check-in** — this is the part of me that doesn't just record; it argues.",
            "",
            f"You wrote you want to *{stalled.get('goal')}*. Last touched **{stalled.get('last_touched','?')}**, "
            f"at ~**{stalled.get('progress')}%** progress.",
        ]
        if themes:
            text.append(f"But the week's narratives are mostly about *{theme}*, not that goal.")
        if journal:
            text.append("Here's what you actually put in your journal:")
            for l in journal:
                text.append(f"  • {l}")
        if overlay:
            text.append(f"And your personal SOUL overlay says: *{overlay}* (truncated).")
        text.append("")
        text.append("I'm not nagging — I'm asking the hard question first, so you don't have to: "
                    "**is that goal still true, or is it a ghost you're carrying?** If it's dead, let it go.")
        return {"challenge": "\n".join(text), "stalled_goal": stalled.get("goal"),
                "themes_top": themes[:2], "journal_evidence": journal,
                "evidence_kind": "goal_behavior"}

    # Fallback #2: insight-action gap
    rate = round((gap.get("action_rate", 0) or 0) * 100)
    text = [
        f"🧠 **Soul check-in** — the one mismatch I can't ignore.",
        "",
        f"In the last stretch you *knew* things — **{gap.get('total_insights',0)} cross-domain insights** surfaced — "
        f"but only **{gap.get('acted',0)}** became action ({rate}% action rate).",
        "",
        f"Your weekly themes keep circling *{theme or 'your usual topics'}*, yet knowing isn't doing.",
        "",
        "I'm not grading you. I'm asking: **an insight only counts when it changes a decision.** "
        "What's one of those you'll convert this week?",
    ]
    return {"challenge": "\n".join(text), "stalled_goal": None,
            "themes_top": themes[:2], "journal_evidence": [],
            "evidence_kind": "insight_action_gap",
            "insight_gap": gap}


def main(argv):
    force = "--force" in argv
    dry = "--dry-run" in argv
    if not force and not dry and within_window(STATE_NAME, DEDUP_HOURS):
        print(json.dumps({"skipped": "within dedup window"}, indent=2))
        return 0

    ch = compose_challenge()
    if not ch:
        print(json.dumps({"no_challenge": "no stalled-goal/behavior contradiction"}, indent=2))
        return 0

    if dry:
        print(json.dumps(ch, indent=2, default=str))
        return 0

    mark_run(STATE_NAME, **{"stalled": ch.get("stalled_goal")})
    ch["telegram"] = page_telegram(ch["challenge"])
    print(json.dumps(ch, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))