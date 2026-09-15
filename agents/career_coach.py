#!/usr/bin/env python3
import json, os, sys, datetime
from pathlib import Path

NAME = "career_coach"
HERMES_HOME = Path(os.path.expanduser("~/.hermes"))
AGENTS_DIR = HERMES_HOME / "agents"
DATA_DIR = HERMES_HOME / "data"
LOGS_DIR = HERMES_HOME / "logs"
STORE_FILE = AGENTS_DIR / NAME / "store.json"
LOG_FILE = LOGS_DIR / "career_coach.log"

def _log(msg):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat()
    with open(LOG_FILE, "a") as f:
        f.write("[%s] %s
" % (timestamp, msg))

def _load_store():
    try:
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if STORE_FILE.exists():
            return json.loads(STORE_FILE.read_text())
    except Exception:
        pass
    return {"items": [], "meta": {}}

def _save_store(data):
    try:
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STORE_FILE.write_text(json.dumps(data, indent=2, sort_keys=True))
    except Exception as e:
        _log("save error: %s" % str(e))

def check():
    data = _load_store()
    due = []
    today = datetime.now().strftime("%Y-%m-%d")
    for it in data.get("items", []):
        if it.get("due") and it.get("due") <= today and not it.get("done"):
            due.append(it)
    if due:
        print("%s: %d item(s) due/overdue" % (NAME, len(due)))
        for it in due[:5]:
            print("  - %s: %s (due %s)" % (it.get("kind", "?"), it.get("name", "?"),
                                           it.get("due", "?")))
    else:
        print("%s: check done - 0 due, 0 overdue" % NAME)
    return 0 if not due else 1

def report():
    data = _load_store()
    print("%s (%s)" % (NAME, "Career Coach Agent"))
    print("tracked items: %d" % len(data.get("items", [])))
    for it in data.get("items", [])[:10]:
        done = "" if it.get("done") else " (open)"
        print("  - %s: %s due %s%s" % (it.get("kind", "?"), it.get("name", "?"),
                                       it.get("due", "n/a"), done)")

STAR_COACHING = "STAR Method Coaching:

Situation: Describe the context or challenge you faced.
Task: What was your responsibility?
Action: Specifically what did YOU do (not what 'the team' did).
Result: Quantify the outcome (metrics, results, impact).

Example: 'Situation: Our project was behind schedule. Task: I needed to recover 2 weeks. Action: I re-prioritized backlog items and added daily standups. Result: We recovered 1.5 weeks and delivered on time.'"

RESUME_GUIDANCE = "Resume Review Guidance:

1. Keep to 1 page (2 max for 10+ years experience)
2. Quantify achievements: 'Increased efficiency by X%' not 'Helped improve'
3. Use reverse chronological order
4. Include keywords from job descriptions
5. Clean formatting, no typos

Example bullet: 'Led team of 5, reduced processing time 30% via automation'"

INTERVIEW_STAR = "Prepare behavioral answers using STAR method. Practice 5-10 common questions: 'Tell me about a time you failed, handled conflict, went above and beyond.'"

INTERVIEW_TECHNICAL = "Prepare for technical questions: data structures, system design, be ready to write code on whiteboard/paper."

INTERVIEW_SALARY = "Research market rates for your role/level. Have a target number. Be prepared to justify with market data and your accomplishments."

SKILL_GUIDANCE = "Skill Gap Analysis:

1. Identify skills required for target roles
2. Assess current skills with honesty
3. Prioritize high-impact skills to develop
4. Choose learning path: formal cert., self-practice, projects
5. Set timeline and accountability mechanism"

LINKEDIN_GUIDANCE = "LinkedIn Profile Optimization:

1. Professional headline with value proposition
2. Summary section: 3-5 paragraphs highlighting key achievements
3. Quantify accomplishments throughout
4. Get 3+ recommendations
5. Customize connection requests
5. Share valuable content regularly
6. Use 'Open to Work' frame strategically"

CAREER_TRANSITION = "Career Transition Framework:

1. Clarify: What do you want? Why? What matters most?
2. Assess: Current skills, network, financial runway
3. Skill bridge: What do you need to learn/close gaps?
4. Test: Informational interviews, side projects, freelancing
5. Execute: Update materials, apply strategically, network
6. Reflect: What worked? What would you do differently?"

CAREER_OVERVIEW = "Career Coaching Overview:

I can help you with:
• STAR method coaching for behavioral interviews
• Resume review and formatting
• Interview preparation (technical, behavioral, salary)
• Skill gap analysis and learning path
• LinkedIn profile optimization
• Career transition planning

What would you like to focus on?"


def _star_coaching(question):
    return STAR_COACHING

def resume_review(profile):
    return RESUME_GUIDANCE

def interview_prep(focus):
    foci = {
        "star": STAR_COACHING,
        "technical": INTERVIEW_TECHNICAL,
        "behavioral": INTERVIEW_STAR,
        "salary": INTERVIEW_SALARY,
    }
    return foci.get(focus, "General interview preparation: research the company, prepare questions for interviewers, practice your narrative, get good rest before the interview.")

def handle_career_query(query):
    q = query.lower().strip()
    if any(tok in q for tok in ["STAR", "situation", "task", "action", "result"]):
        return _star_coaching(query)
    if any(tok in q for tok in ["resume", "cv", "format", "review"]):
        return resume_review(query)
    if any(tok in q for tok in ["interview", "mock", "questions"]):
        return interview_prep(focus or "general")
    if any(tok in q for tok in ["salary", "negotiation", "pay", "raise"]):
        return ("Salary Negotiation Guidance:

"
                "1. Research market rates for your role/level and location
"
                "2. Have a target number and a walk-away number
"
                "3. Prepare market data: levels.fyi, Glassdoor, Payscale
"
                "3. Anchor with your accomplishments: 'Based on X achievement, market rate is Y'
"
                "4. Be comfortable with silence after stating your number
"
                "5. Consider total compensation: benefits, equity, work-life")
    if any(tok in q for tok in ["skill gap", "upskill", "re-skill", "certification"]):
        return SKILL_GUIDANCE
    if any(tok in q for tok in ["linkedin", "profile", "network"]):
        return LINKEDIN_GUIDANCE
    if any(tok in q for tok in ["career transition", "career change", "pivot", "new role"]):
        return CAREER_TRANSITION
    return CAREER_OVERVIEW


def main():
    if len(sys.argv) < 2:
        print("usage: career_coach.py {check|report| STAR|resume|interview|salary|skill|linkedin|transition}")
        print()
        print("Commands:")
        print("  check    - Check due items/action items")
        print("  report   - Report current state")
        print("  STAR     - STAR method coaching for behavioral questions")
        print("  resume   - Resume review guidance")
        print("  interview - Interview preparation")
        print("  salary   - Salary negotiation guidance")
        print("  skill    - Skill gap analysis")
        print("  linkedin - LinkedIn profile optimization")
        print("  transition - Career transition framework")
        return 1

    cmd = sys.argv[1]

    if cmd == "check":
        return check()
    if cmd == "report":
        return report()

    query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
    if not query:
        print("Missing query. Usage: career_coach.py {STAR|resume|interview|salary|skill|linkedin|transition} <question>")
        return 1

    result = handle_career_query(query)
    print(result)
    return 0

if __name__ == "__main__":
    sys.exit(main())
