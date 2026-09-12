"""career_coach_data.py — Career Coach store, competency model, scoring, and banks.

Target profile: Director Program Management / Program Direction / Delivery Management.
State: ~/.hermes/state/career_coach; Story bank: ~/.hermes/data/career/coach/stories.jsonl.
"""

from __future__ import annotations

import json
import os
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
STATE_DIR = HERMES_HOME / "state" / "career_coach"
DATA_DIR = HERMES_HOME / "data" / "career" / "coach"
STORY_BANK = DATA_DIR / "stories.jsonl"
INTERVIEW_LOG = STATE_DIR / "interview_log.jsonl"
LINKEDIN_LOG = STATE_DIR / "linkedin.jsonl"
WEEKLY_FILE = STATE_DIR / "weekly.json"
PROFILE_FILE = STATE_DIR / "profile.json"
NARRATIVES_FILE = DATA_DIR / "narratives.md"

COMPETENCIES = [
    "Program Strategy & Portfolio",
    "Delivery at Scale",
    "Stakeholder & Executive Communication",
    "Financial & Commercial",
    "Risk, Dependency & Governance",
    "Leadership & Talent",
]

KEYWORDS = {
    "Program Strategy & Portfolio": ["portfolio", "program strategy", "roadmap", "prioritize", "prioritisation",
                                     "business case", "outcomes", "value realization", "investment", "ambition",
                                     "vision", "multi-year", "program roadmap"],
    "Delivery at Scale": ["scale", "multi-team", "cross-functional", "delivery", "milestones", "sprint", "agile",
                          "waterfall", "predictability", "on-time", "release", "epic", "dependencies", "program",
                          "cd pipeline", "complex delivery"],
    "Stakeholder & Executive Communication": ["stakeholder", "executive", "steerco", "steering", "board", "c-suite",
                                              "ceo", "cto", "presentation", "communicat", "influence", "escalation",
                                              "upward", "negotia", "readback", "narrativ"],
    "Financial & Commercial": ["budget", "cost", "financial", "forecast", "revenue", "profit", "saving", "tco",
                               "vendor", "contract", "sow", "procurement", "financ", "margin", "roi", "capex",
                               "opex", "chargeback", "license"],
    "Risk, Dependency & Governance": ["risk", "raid", "dependency", "governance", "compliance", "audit", "control",
                                      "mitigat", "incident", "resilience", "disaster", "continuity", "security",
                                      "regulatory", "gate", "tollgate"],
    "Leadership & Talent": ["team", "hire", "talent", "coach", "mentor", "org design", "restructure", "people",
                            "retention", "onboard", "underperform", "promote", "career growth", "leadership",
                            "culture", "r&r", "recognition"],
}

QUESTION_BANK = {
    "Program Strategy & Portfolio": [
        "Walk me through how you would set the strategy for a new program. How do you define success and align it to business outcomes?",
        "Tell me about a time you had to prioritize across competing programs. How did you decide, and what did the portfolio lose?",
        "Describe how you would build a 12-18 month program roadmap and then keep it credible with executives.",
        "How do you measure the value of a program beyond delivery milestones? Give a concrete example.",
        "You are handed a portfolio where every program is optimistic. How do you re-baseline and gain stakeholder agreement?",
    ],
    "Delivery at Scale": [
        "Tell me about the largest program you have delivered. What made it complex, and how did you keep it predictable?",
        "Describe a time a delivery was going off the rails. What were the signals, and what did you do?",
        "How do you handle dependency chains across many teams, and getting them committed at the right time?",
        "What is your framework for running a large, multi-stream delivery cadence?",
        "Give me an example where you reduced delivery time or cost materially. What levers did you pull first?",
    ],
    "Stakeholder & Executive Communication": [
        "Describe how you run an executive steering committee and keep it from becoming a status meeting.",
        "Tell me about a time you got a heavyweight stakeholder to change their mind. What did you do?",
        "How do you present bad news to leadership — cost overrun or a slipped date? Give a real example.",
        "How do you build trust with executives in the first 90 days of a new program?",
        "Describe a time you had to influence someone with more authority than you.",
    ],
    "Financial & Commercial": [
        "Tell me about a time you managed a program budget. How did you forecast, track, and defend it?",
        "How would you build a business case for a new initiative and then defend it through investment review?",
        "Describe a time you delivered a significant cost saving or got a better outcome from a vendor.",
        "How do you manage financial risk on a program — unplanned cost, scope growth, procurement slippage?",
        "Walk me through a program where the commercial model (vendor, delivery model) mattered to the outcome.",
    ],
    "Risk, Dependency & Governance": [
        "Tell me about a hidden risk you spotted early and how you handled it before it became an issue.",
        "How do you run RAID, and what is the difference between a risk you track and a risk you act on?",
        "Describe a time governance slowed you down. How did you work within or change it?",
        "How would you recover a program after an incident or a failed dependency?",
        "Walk me through your approach to change control and keeping a program compliant under pressure.",
    ],
    "Leadership & Talent": [
        "Tell me about a time you built or reshaped a team to deliver a challenging program.",
        "How do you coach a program manager who is underperforming? Concrete example.",
        "Describe how you make a decision that the team disagrees with, and how you keep their energy after.",
        "How do you develop talent around you, and what have you promoted that you are proud of?",
        "Tell me about a time you led through a reorg or significant organizational change.",
    ],
}

GENERIC_QUESTIONS = [
    "Tell me about yourself — frame it as a program/delivery leader, not a resume read.",
    "What is the biggest program failure you have been part of, and what did you learn?",
    "How do you say no to a stakeholder who wants scope added to an already full program?",
    "Describe a time you decided under real uncertainty with incomplete data.",
    "Tell me about the program outcome you are most proud of and why it mattered.",
    "What would your team and your steering committee each say about you, honestly?",
]

PROMPTS = {
    "title": "Give the story a headline — the one-liner you would say in an interview to hook attention.",
    "situation": "SITUATION: the context and pressure around you. What was at stake?",
    "task": "TASK: what were YOU responsible for (not the team, you)?",
    "action": "ACTION: 2-4 concrete steps YOU took. Be specific and personal.",
    "result": "RESULT: what changed? Include numbers — %, $, time, people, scope.",
    "tags": "Which 1-3 competencies fit best? Choose from: " + ", ".join(COMPETENCIES) + ".",
}

HEDGES = ["somewhat", "maybe", "kind of", "sort of", "just", "basically", "actually", "i think", "i feel",
          "probably", "perhaps", "a bit", "relatively", "quite", "fairly", "i guess", "tends to"]
VAGUE_WORDS = ["many", "some", "a lot", "several", "lots", "big", "large", "small", "good", "nice", "fine",
               "well", "better", "a while", "quickly", "slowly", "eventually", "shortly", "much", "more",
               "less", "stuff", "things", "great"]
_METRIC_RE = re.compile(
    r"\b\d+(\.\d+)?\s*(%|\$|million|million|m|k|people|users|teams|months|quarter|quarters|years|weeks|days"
    r"|sprints|projects|programs|locations|countries|regions|vendors|budget|revenue|cost|headcount|streams|"
    r"epics|gateways|containers|servers)\b|\$\s?\d|%",
    re.IGNORECASE,
)
_PASSIVE_RE = re.compile(r"\b(was|were|been|is|are|being)\s+(\w+ed)\b", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_stories() -> list:
    _ensure()
    if not STORY_BANK.exists():
        return []
    out = []
    for line in STORY_BANK.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def save_story(story: dict) -> dict:
    _ensure()
    rows = []
    replaced = False
    for line in STORY_BANK.read_text().splitlines() if STORY_BANK.exists() else []:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("id") == story.get("id"):
            rows.append(story)
            replaced = True
        else:
            rows.append(row)
    if not replaced:
        rows.append(story)
    STORY_BANK.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""))
    return story


def add_story(fields: dict) -> dict:
    _ensure()
    existing = load_stories()
    taken = {s.get("id") for s in existing}
    n = 1
    while f"story_{n:03d}" in taken:
        n += 1
    story = {
        "id": f"story_{n:03d}",
        "title": str(fields.get("title", "")).strip(),
        "situation": str(fields.get("situation", "")).strip(),
        "task": str(fields.get("task", "")).strip(),
        "action": str(fields.get("action", "")).strip(),
        "result": str(fields.get("result", "")).strip(),
        "metrics": str(fields.get("metrics", "")).strip(),
        "competencies": fields.get("competencies", []) or [],
        "confidence": 0,
        "created_at": _now(),
        "updated_at": _now(),
        "last_used": "",
    }
    gate = quality_gate(story)
    story["confidence"] = gate["confidence"]
    save_story(story)
    return story


def get_story(story_id: str) -> dict | None:
    for s in load_stories():
        if s.get("id") == story_id:
            return s
    return None


def refine_story(story_id: str, field: str, value: str) -> dict | None:
    story = get_story(story_id)
    if not story:
        return None
    if field not in ("title", "situation", "task", "action", "result", "metrics", "competencies"):
        return None
    if field == "competencies":
        story[field] = [c.strip() for c in value.split(",") if c.strip()]
    else:
        story[field] = value.strip()
    story["updated_at"] = _now()
    gate = quality_gate(story)
    story["confidence"] = gate["confidence"]
    save_story(story)
    return story


def suggest_competencies(text: str) -> list:
    low = text.lower()
    hits = []
    for comp, words in KEYWORDS.items():
        score = sum(1 for w in words if w in low)
        if score:
            hits.append((comp, score))
    hits.sort(key=lambda x: -x[1])
    return [c for c, _ in hits[:3]] or ["Delivery at Scale"]


def _metric_count(text: str) -> int:
    return len(re.findall(r"\d+", (text or "") + " ")) * 2 + len(_METRIC_RE.findall(text or "")) * 3


def quality_gate(story: dict) -> dict:
    attrs = [story.get("situation", ""), story.get("task", ""), story.get("action", ""), story.get("result", "")]
    filled = sum(1 for a in attrs if len(str(a).strip()) >= 30)
    structure = 0 if filled == 0 else (2 if filled == 1 else (3 if filled == 2 else (4 if filled == 3 else 5)))
    action = str(story.get("action", ""))
    has_actions = len([w for w in re.split(r"[.\n;,]", action) if "ed" in w.lower() or w.strip()]) >= 3 or len(action) >= 60
    if not has_actions and filled == 4:
        structure = max(3, structure - 1)
    words = " ".join(attrs).split()
    sentences = [s for s in re.split(r"[.!?]", " ".join(attrs)) if len(s.split()) >= 3]
    avg_len = (sum(len(s.split()) for s in sentences) / len(sentences)) if sentences else 0
    metric_count = _metric_count(story.get("result", "") + " " + story.get("metrics", ""))
    metrics = min(5, metric_count // 2) if metric_count else 0
    concreteness = min(5, 1 + filled + (1 if any(c.isdigit() for c in story.get("result", "")) else 0))
    sentiment = 0
    impact_words = ["achieved", "delivered", "reduced", "increased", "saved", "launched", "grew", "improved",
                    "on time", "ahead", "exceeded", "transformed", "stabilized", "accelerated"]
    for w in impact_words:
        if w in (" ".join(attrs)).lower():
            sentiment += 1
    impact = min(5, sentiment + (1 if metric_count else 0))
    confidence = round(statistics.mean([structure, concreteness, metrics, impact]), 1) if filled else 0.0
    hints = []
    if filled < 4:
        hints.append("Add the missing STAR element(s): " + ", ".join(
            k for k, v in zip(["situation", "task", "action", "result"], attrs) if len(str(v).strip()) < 30))
    if metric_count == 0:
        hints.append("No numbers found — add at least one concrete metric (%, $, time, or people).")
    if avg_len and avg_len > 40:
        hints.append(f"Long sentences (avg {avg_len:.0f} words) — break them up for spoken delivery.")
    if not story.get("competencies"):
        hints.append("No competency tags yet.")
    return {"structure": structure, "concreteness": concreteness, "metrics": metrics, "impact": impact,
            "confidence": confidence, "hints": hints}


def coach_text(text: str) -> dict:
    low = (text or "").lower()
    flags = []
    hedge_hits = [h for h in HEDGES if h in low]
    vague_hits = [v for v in VAGUE_WORDS if re.search(r"\b" + re.escape(v) + r"\b", low)]
    passive_hits = len(_PASSIVE_RE.findall(text or ""))
    metric_count = _metric_count(text or "")
    sentences = [s for s in re.split(r"[.!?]", text or "") if len(s.split()) >= 3]
    avg_len = (sum(len(s.split()) for s in sentences) / len(sentences)) if sentences else 0
    words = len((text or "").split())
    structure = 0
    structure += 1 if re.search(r"(situation|context|backgr|environment)", low) else 0
    structure += 1 if re.search(r"\b(i( was| had| owned| led| decided| built| ran| took| drove))", low) else 0
    structure += 1 if metric_count else 0
    structure += 1 if re.search(r"\b(i|so|we|the (result|outcome|impact))", low) and metric_count else 0
    structure += 1 if re.search(r"\b(i|outcome|result|as a (result|consequence)|bottom line)", low) else 0
    metrics = min(5, metric_count // 2) if metric_count else 0
    clarity = 5
    clarity -= min(3, len(hedge_hits))
    clarity -= min(2, len(vague_hits) // 2)
    if avg_len > 40:
        clarity -= min(2, int(avg_len // 25))
    clarity = max(0, min(5, clarity))
    impact = min(5, metric_count // 2)
    for w in ["delivered", "reduced", "increased", "saved", "launched", "exceeded", "transformed", "stabilized"]:
        if w in low:
            impact += 1
    impact = max(0, min(5, impact))
    tips = []
    if hedge_hits:
        tips.append("Remove hedge words: " + ", ".join(hedge_hits[:4]))
    if vague_hits:
        tips.append("Replace vague quantifiers with numbers: " + ", ".join(vague_hits[:4]))
    if passive_hits:
        tips.append(f"{passive_hits} passive phrase(s) — switch to active 'I did X'.")
    if metric_count == 0:
        tips.append("Add a metric — numbers carry the impact.")
    if structure < 3:
        tips.append("Follow S-T-A-R: situation → your task → your actions → result with a number.")
    if avg_len > 40:
        tips.append(f"Average sentence {avg_len:.0f} words — for speaking, target under 25.")
    return {"structure": structure, "metrics": metrics, "clarity": clarity, "impact": impact,
            "hedges": hedge_hits, "vague": vague_hits, "passive": passive_hits,
            "avg_sentence_words": round(avg_len, 1), "word_count": words,
            "scores": {"structure": structure, "metrics": metrics, "clarity": clarity, "impact": impact},
            "tips": tips}


def score_answer(text: str, competency: str = "") -> dict:
    analysis = coach_text(text)
    dims = analysis["scores"]
    overall = round(statistics.mean(dims.values()), 1) if dims else 0.0
    row = {
        "when": _now(),
        "competency": competency or "generic",
        "word_count": analysis["word_count"],
        "dims": dims,
        "overall": overall,
        "hedges": len(analysis["hedges"]),
        "raw": text,
    }
    _ensure()
    with INTERVIEW_LOG.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def pick_question(competency: str = "") -> dict:
    if competency and competency in QUESTION_BANK:
        pool = QUESTION_BANK[competency]
    elif competency == "generic":
        pool = GENERIC_QUESTIONS
    else:
        pool = GENERIC_QUESTIONS
    return {"competency": competency or "generic", "question": pool[len(pool) % len(pool)]}


def _stories_with_scores(stories: list) -> list:
    for s in stories:
        s.setdefault("confidence", 0)
    ranked = sorted(stories, key=lambda s: (-s.get("confidence", 0), -_metric_count(str(s.get("result", "")))))
    return ranked


def deep_dive() -> dict:
    _ensure()
    stories = load_stories()
    ranked = _stories_with_scores(stories)
    coverage = {c: [_ for _ in ranked if c in (_.get("competencies") or [])] for c in COMPETENCIES}
    gaps = [c for c, ss in coverage.items() if len(ss) < 2]
    rich = [s for s in ranked if s.get("confidence", 0) >= 3.0 and _metric_count(str(s.get("result", "")))]
    top = ranked[:3]
    lines = [
        "# Career Deep-Dive Narratives",
        "",
        f"Generated {_now()}  |  {len(stories)} stories banked, {len(rich)} metric-rich.",
        "",
        "## Tell me about yourself (90-second opening)",
        "",
    ]
    if top:
        track = " and ".join(s.get("title", "") for s in top[1:])
        opening = (
            f"I have spent my career landing complex programs on time and on budget. "
            f"Most recently: {top[0].get('title', '')}, where {top[0].get('result', '')}."
        )
        if track:
            opening += f" Earlier track record: {track}. "
        opening += ("Underpinning all of it: a program strategy tied to business outcomes, tight financial control, "
                    "and stakeholder communication that keeps executives ahead of surprises.")
        lines.append(opening)
    else:
        lines.append("_No strong stories yet — capture your best program outcome first._")
    lines.append("")
    lines.append("## 60-second version")
    lines.append("")
    lines.append(top[0].get("result", "Capture S+T first.") if top else "_Bank a story to unlock this._")
    lines.append("")
    lines.append("## 3-minute version (metrics + depth stories)")
    lines.append("")
    for s in ranked[:2]:
        lines.append(f"- **{s.get('title')}** — {s.get('situation', '')[:200]} → {s.get('result', '')[:200]}")
    lines.append("")
    lines.append("## Coverage and gaps")
    lines.append("")
    for c in COMPETENCIES:
        n = len(coverage[c])
        lines.append(f"- {c}: {n} story" + ("s" if n != 1 else "") + ("  ⚠️ GAP" if n < 2 else ""))
    lines.append("")
    lines.append("## Focus next")
    lines.append("")
    lines.append(", ".join(gaps) if gaps else "All competencies have at least two stories — start depth-building.")
    NARRATIVES_FILE.write_text("\n".join(lines))
    return {"stories": len(stories), "gaps": gaps, "top_story": top[0].get("title", "") if top else "",
            "metric_rich": len(rich)}


def linkedin_suggest(stats_only: bool = False) -> dict:
    _ensure()
    stories = load_stories()
    ranked = _stories_with_scores(stories)
    strong = [s for s in ranked if s.get("confidence", 0) >= 3.0][:3]
    if stats_only:
        return {"strong_stories": len(strong), "stories": len(stories)}
    headline = "Director Program Management | " 
    if strong:
        headline += " | ".join(str(s.get("result", ""))[:70] for s in strong[:2])
    headline = headline.rstrip(" |")[:110]
    about_lines = [
        "Program and delivery leader who takes complex, multi-stream programs from ambiguity to value.",
    ]
    for s in strong[:2]:
        about_lines.append(f"- {s.get('title', '')}: {s.get('result', '')}")
    outreach = (
        "Hi {{first_name}} — I run programs that land complex delivery on time and on budget; I see you "
        "lead at {{company}} and would value a quick 15-min intro on how your PMO sets up programs for success."
    )
    idea = ""
    if strong:
        s = strong[0]
        idea = f"Post idea from your story bank: 'How we {s.get('task', '')[:60]} — and the numbers that made leadership believe it.'"
    row = {"when": _now(), "headline": headline, "stories_used": [s.get("title") for s in strong]}
    with LINKEDIN_LOG.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"headline": headline, "about": "\n".join(about_lines), "outreach": outreach, "content_idea": idea}


def weekly_review() -> dict:
    _ensure()
    stories = load_stories()
    interviews = []
    if INTERVIEW_LOG.exists():
        for line in INTERVIEW_LOG.read_text().splitlines():
            if line.strip():
                try:
                    interviews.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    linkedin = link_actions_count()
    by_comp = {}
    for s in stories:
        for c in s.get("competencies", []):
            by_comp.setdefault(c, []).append(s.get("confidence", 0))
    comp_coverage = {c: len(by_comp.get(c, [])) for c in COMPETENCIES}
    weakest = None
    if interviews:
        comp_scores = {}
        for r in interviews:
            comp_scores.setdefault(r.get("competency", "generic"), []).append(r.get("overall", 0))
        weakest = min(comp_scores, key=lambda c: statistics.mean(comp_scores[c])) if comp_scores else None
    avg_iv = round(statistics.mean([r.get("overall", 0) for r in interviews]), 1) if interviews else None
    avg_words = round(statistics.mean([r.get("word_count", 0) for r in interviews]), 1) if interviews else None
    report = {
        "when": _now(),
        "stories": len(stories),
        "avg_confidence": round(statistics.mean([s.get("confidence", 0) for s in stories]), 1) if stories else 0,
        "comp_coverage": comp_coverage,
        "interviews": len(interviews),
        "avg_interview_score": avg_iv,
        "avg_answer_words": avg_words,
        "weakest_competency": weakest,
        "linkedin_actions": linkedin,
    }
    WEEKLY_FILE.write_text(json.dumps(report, indent=2))
    return report


def link_actions_count() -> int:
    _ensure()
    if not LINKEDIN_LOG.exists():
        return 0
    return sum(1 for line in LINKEDIN_LOG.read_text().splitlines() if line.strip())


def profile() -> dict:
    _ensure()
    if PROFILE_FILE.exists():
        try:
            return json.loads(PROFILE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    default_profile = {
        "name": "Rohit Mishra",
        "target_roles": ["Director Program Management", "Program Director",
                         "Director Project Management", "Director Delivery Management"],
        "level": "Director",
        "linkedin": "",
        "resume": "data/career/",
        "updated": _now(),
    }
    PROFILE_FILE.write_text(json.dumps(default_profile, indent=2))
    return default_profile


def daily_prompt() -> dict:
    _ensure()
    import datetime as _dt
    today = _dt.date.today()
    stories = load_stories()
    idx = today.isoweekday()
    labels = {1: "new", 2: "refine", 3: "new", 4: "coach", 5: "refine", 6: "linkedin", 7: "rest"}
    mode = labels.get(idx, "coach")
    text = ""
    if mode == "new":
        text = ("🎯 Coach: time to bank one story — the program you are most proud of. "
                "Reply /story and we will walk through it (S-T-A-R + a number).")
    elif mode == "refine":
        stories = sorted(stories, key=lambda s: s.get("confidence", 0))
        target = stories[0] if stories else None
        text = (f"🎯 Coach: let's sharpen the weakest story today — “{target.get('title')}” "
                f"(confidence {target.get('confidence')}/5). Reply /story show {target.get('id')} then /story refine "
                "to improve one field.") if target else "🎯 Coach: no stories yet — reply /story to bank your first one."
    elif mode == "coach":
        text = ("🎯 Coach: send me any 90-second answer (paste text) and I will score structure, "
                "metrics, clarity and impact, and give rewrites. Try: a real interview answer of yours.")
    elif mode == "linkedin":
        text = "🎯 Coach: LinkedIn day — reply /linkedin to get a headline, About draft, and an outreach template."
    else:
        text = "🎯 Coach: rest day. Optionally reply /mock for a practice question."
    return {"mode": mode, "text": text}