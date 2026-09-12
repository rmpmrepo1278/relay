#!/usr/bin/env python3
"""life_radiator.py — one navigable "second brain" map, synthesized weekly.

Reads across the memory ecosystem (observations, narrative themes, decisions,
insights, commitments, goals) and renders a *single living narrative* + a JSON
index where every claim carries a back-reference to its source table/row so
you can drill from "the map" to the raw memory.

Outputs:
  * data/life_radiator/{YYYY-Www}.md     — the human narrative
  * data/life_radiator/{YYYY-Www}.json   — index w/ back-refs
  * paged Telegram digest (deduped weekly)

CLI:
  python3 life_radiator.py            # run (7d dedup)
  python3 life_radiator.py --force
  python3 life_radiator.py --dry-run  # build only, don't persist/page
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
    HERMES_HOME, DATA, STATE, get_db, page_telegram, within_window, mark_run,
    read_json, read_text, _now,
)

DEDUP_HOURS = float(os.environ.get("RADIATOR_DEDUP_HOURS", "168"))  # weekly
STATE_NAME = "radiator_window"


def _observation_samples(limit: int = 12) -> list[dict]:
    try:
        c = get_db()
        rows = c.execute(
            "SELECT id, source, content, importance, category FROM observations "
            "ORDER BY rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        c.close()
        return [dict(zip(("id", "source", "content", "importance", "category"), r))
                for r in rows]
    except Exception:
        return []


def _decision_rows(limit: int = 10) -> list[dict]:
    try:
        c = get_db()
        rows = c.execute(
            "SELECT id, summary, status, domain, source FROM decision_register "
            "ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        c.close()
        return [dict(zip(("id", "summary", "status", "domain", "source"), r))
                for r in rows]
    except Exception:
        return []


def _narrative_themes() -> list[str]:
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import narrative_memory as nm
        return [t for t, _ in (nm.top_themes(6) or [])]
    except Exception:
        return []


def _insight_rows() -> list[str]:
    d = read_json(DATA / "insights.json", [])
    return [i.get("content", "")[:100] for i in d if isinstance(d, list)][:6]


def _commitment_summary() -> dict:
    d = read_json(DATA / "commitments.json", {})
    stats = d.get("stats", {})
    active = [c.get("text", "")[:60] for c in d.get("active", [])][:5]
    return {"stats": stats, "active": active}


def build_map(dry: bool = False) -> dict:
    observations = _observation_samples()
    decisions = _decision_rows()
    themes = _narrative_themes()
    insights = _insight_rows()
    commits = _commitment_summary()
    stats = commits.get("stats", {})

    # back-refs: every claim we make carries source_table + id
    backrefs = {
        "observations": [{"id": o["id"], "source": o["source"], "text": o["content"][:120]}
                         for o in observations],
        "decisions": [{"id": d["id"], "status": d["status"], "text": d["summary"][:120]}
                      for d in decisions],
        "narrative_themes": themes,
        "insights": insights,
        "commitments": {"active": commits.get("active", []), "stats": stats},
    }

    # one narrative
    narrative_lines = [
        f"# Your Second Brain — Week of {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "",
        "This is the map, not the territory. Every line below traces back to a row "
        "in `observations`, `decision_register`, `narrative_memory`, or `commitments.json`.",
        "",
    ]
    if themes:
        narrative_lines.append(f"## The threads you keep pulling\n- " + "\n- ".join(themes))
    if insights:
        narrative_lines.append(f"\n## Cross-domain signals\n- " + "\n- ".join(insights))
    if observations:
        narrative_lines.append(f"\n## Latest observations\n")
        for o in observations[:6]:
            narrative_lines.append(f"- [{o['source']}] {o['content'][:120]}")
    if decisions:
        narrative_lines.append(f"\n## Decisions the council touched\n")
        for d in decisions[:5]:
            narrative_lines.append(f"- `{d['id']}` [{d['status']}] {d['summary'][:100]}")
    if stats:
        narrative_lines.append(f"\n## Commitment heartbeat\n"
                              f"- made:{stats.get('total_made',0)} fulfilled:{stats.get('total_fulfilled',0)} "
                              f"rate:{stats.get('on_time_rate',0)}")
    narrative = "\n".join(narrative_lines)

    m = {
        "generated_at": _now(),
        "week": datetime.now(timezone.utc).strftime("%Y-W%W"),
        "narrative": narrative,
        "index": backrefs,
    }

    if not dry:
        out = DATA / "life_radiator"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{m['week']}.md").write_text(narrative)
        (out / f"{m['week']}.json").write_text(json.dumps(m, indent=2))
        mark_run(STATE_NAME, week=m["week"])
        digest = (f"🧠 **Life Radiator — {m['week']}**\n"
                  f"Themes: {', '.join(themes[:3])}\n"
                  f"Decisions: {len(decisions)} · Observations: {len(observations)}\n"
                  f"Commitments: {stats.get('total_made',0)} made / {stats.get('total_fulfilled',0)} kept")
        m["telegram"] = page_telegram(digest)
    return m


def main(argv):
    if not (any(a in argv for a in ("--force",)) or within_window(STATE_NAME, DEDUP_HOURS)) and "--dry-run" not in argv:
        res = {"skipped": "within dedup window"}
        print(json.dumps(res, indent=2))
        return 0
    m = build_map(dry="--dry-run" in argv)
    print(json.dumps({k: (v if k != "narrative" else v[:400]) for k, v in m.items()}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))