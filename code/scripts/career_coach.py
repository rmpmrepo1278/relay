#!/usr/bin/env python3
"""career_coach.py — Career Coach CLI + Telegram-send orchestration.

Subcommands:
  add --json {...}                  add a story
  list                              list stories (id, title, confidence)
  show <id>                         show one story
  refine <id> --field F --value V   update one field
  gate <id>                         re-run the quality gate
  coach --text "..."                speaking coach on any answer text
  question [--competency C]         emit one interview question
  score --text "..." [--competency C]  score an answer (logs to interview_log)
  mock [--competency C]             interactive mock interview (stdin/stdout)
  deep-dive                         rebuild narratives.md
  linkedin                          LinkedIn headline/about/outreach draft
  weekly                            weekly review report
  daily-prompt                      cadence prompt (scheduler) + Telegram send
  weekly-send                       weekly review + Telegram send
  selftest                          run sanity checks
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import career_coach_data as data  # noqa: E402


def _load_env() -> dict:
    env = {}
    p = Path.home() / ".hermes" / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _tg_send(text: str) -> dict:
    env = _load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel = env.get("TELEGRAM_HOME_CHANNEL", "")
    if not token or not channel:
        return {"sent": False, "reason": "no telegram creds"}
    thread_id = None
    if ":" in channel:
        channel, _, thread_id = channel.partition(":")
    payload = {"chat_id": channel, "text": text[:4000], "parse_mode": "Markdown"}
    if thread_id:
        try:
            payload["message_thread_id"] = int(thread_id)
        except ValueError:
            pass
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return {"sent": result.get("ok", False)}
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "reason": str(exc)}


def _fmt_gate(g) -> dict:
    return {
        "confidence": g["confidence"],
        "structure": f"{g['structure']}/5",
        "concreteness": f"{g['concreteness']}/5",
        "metrics": f"{g['metrics']}/5",
        "impact": f"{g['impact']}/5",
        "hints": g["hints"],
    }


def _story_line(s: dict) -> str:
    return f"{s.get('id')}  {s.get('title', '')}  [conf {s.get('confidence')}/5  tags: {', '.join(s.get('competencies', [])) or '-'}]"


def cmd_add(args) -> int:
    if args.json:
        try:
            fields = json.loads(args.json)
        except json.JSONDecodeError:
            print("invalid --json")
            return 2
    elif args.json_file:
        try:
            fields = json.loads(Path(args.json_file).read_text())
        except (OSError, json.JSONDecodeError):
            print(f"invalid --json-file {args.json_file}")
            return 2
    else:
        print("need --json or --json-file")
        return 2
    story = data.add_story(fields)
    print(json.dumps({"id": story["id"], "title": story["title"],
                      "gate": _fmt_gate(data.quality_gate(story))}, indent=2))
    return 0


def cmd_list(args) -> int:
    stories = data.load_stories()
    if not stories:
        print("No stories banked yet.")
        return 0
    for s in stories:
        print(_story_line(s))
    return 0


def cmd_show(args) -> int:
    s = data.get_story(args.id)
    if not s:
        print(f"no story {args.id}")
        return 1
    print(json.dumps(s, indent=2, ensure_ascii=False))
    for line in data.quality_gate(s).get("hints", []):
        print("hint:", line)
    return 0


def cmd_refine(args) -> int:
    s = data.refine_story(args.id, args.field, args.value)
    if not s:
        print(f"no story {args.id} or bad field {args.field}")
        return 1
    print(json.dumps({"id": s["id"], "field": args.field, "gate": _fmt_gate(data.quality_gate(s))}, indent=2))
    return 0


def cmd_gate(args) -> int:
    s = data.get_story(args.id)
    if not s:
        print(f"no story {args.id}")
        return 1
    print(json.dumps(_fmt_gate(data.quality_gate(s)), indent=2, ensure_ascii=False))
    return 0


def cmd_coach(args) -> int:
    analysis = data.coach_text(args.text)
    print(json.dumps(analysis, indent=2, ensure_ascii=False))
    return 0


def cmd_question(args) -> int:
    q = data.pick_question(args.competency)
    print(q["competency"])
    print(q["question"])
    return 0


def cmd_score(args) -> int:
    row = data.score_answer(args.text, args.competency)
    print(json.dumps({"overall": row["overall"], "dims": row["dims"], "words": row["word_count"],
                      "logged": str(data.INTERVIEW_LOG)}, indent=2))
    return 0


def cmd_mock(args) -> int:
    q = data.pick_question(args.competency)
    print(f"[{q['competency']}]\n{q['question']}\n")
    answer = ""
    print("Type your answer, then press Enter twice to submit.")
    while True:
        line = input()
        if line == "" and answer:
            break
        answer += line + "\n"
    row = data.score_answer(answer, q["competency"])
    print("\n--- coach feedback ---")
    print(json.dumps({"overall": row["overall"], "dims": row["dims"], "tips": data.coach_text(answer)["tips"],
                      "next": data.pick_question().get("question")}, indent=2, ensure_ascii=False))
    return 0


def cmd_deep_dive(args) -> int:
    result = data.deep_dive()
    print(json.dumps(result, indent=2))
    print("narratives:", data.NARRATIVES_FILE)
    return 0


def cmd_linkedin(args) -> int:
    result = data.linkedin_suggest()
    print("HEADLINE:"); print(result["headline"])
    print("\nABOUT:"); print(result["about"])
    print("\nOUTREACH:"); print(result["outreach"])
    if result.get("content_idea"):
        print("\nCONTENT IDEA:"); print(result["content_idea"])
    return 0


def cmd_weekly(args) -> int:
    report = data.weekly_review()
    print(json.dumps(report, indent=2))
    return 0


def cmd_daily_prompt(args) -> int:
    result = data.daily_prompt()
    text = result["text"]
    send = _tg_send(text)
    print(text)
    print("telegram:", send)
    return 0


def cmd_weekly_send(args) -> int:
    report = data.weekly_review()
    text = (
        f"📊 **Career Coach weekly review**\n"
        f"- Stories banked: {report['stories']} (avg confidence {report['avg_confidence']}/5)\n"
        f"- Interviews this period: {report['interviews']}, avg {report['avg_interview_score'] or '-'}/5, "
        f"avg answer {report['avg_answer_words'] or '-'} words\n"
        f"- Weakest competency: {report['weakest_competency'] or 'n/a'}\n"
        f"- LinkedIn actions: {report['linkedin_actions']}\n"
    )
    cov = report.get("comp_coverage", {})
    missing = [c for c, n in cov.items() if n < 2]
    if missing:
        text += f"- Coverage gaps (need ≥2 stories): {', '.join(missing)}\n"
    text += "\nNext: /mock to practice, /story to bank more."
    send = _tg_send(text)
    print("telegram:", send)
    print(text)
    return 0


def cmd_selftest(args) -> int:
    ok = True
    def check(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and cond

    s = data.add_story({"title": "selftest story", "situation": "a difficult program with tight timelines",
                        "task": "restore delivery predictability across five teams",
                        "action": "I rebuilt the plan, introduced weekly steerco, cut scope with the sponsor",
                        "result": "delivered 12% under budget, 3 weeks early", "metrics": "12% under, 3 weeks early",
                        "competencies": ["Delivery at Scale"]})
    check("story added", s.get("id", "").startswith("story_") and s.get("confidence", 0) > 0)
    check("get story", data.get_story(s["id"]) is not None)
    refined = data.refine_story(s["id"], "title", "selftest title v2")
    check("refine story", refined is not None and refined["title"] == "selftest title v2")
    gate = data.quality_gate(s)
    check("gate metrics", gate["metrics"] >= 3)
    analysis = data.coach_text("I think we maybe delivered somewhat well and a lot of teams liked it")
    check("coach hedges detected", len(analysis["hedges"]) >= 3)
    check("coach clarity penalized", analysis["clarity"] < 5)
    check("suggest competencies", "Delivery at Scale" in data.suggest_competencies("multi-team agile delivery cadence"))
    row = data.score_answer("we delivered the program 3 weeks ahead and saved 12% through renegotiation",
                            "Delivery at Scale")
    check("score logged", row["overall"] >= 2)
    d = data.deep_dive()
    check("deep-dive has gaps list", isinstance(d["gaps"], list))
    li = data.linkedin_suggest()
    check("linkedin headline long enough", len(li["headline"]) > 20)
    w = data.weekly_review()
    check("weekly report has stories count", "stories" in w)
    clean = [x for x in data.load_stories() if x.get("title", "").startswith("selftest")]
    for x in clean:
        data.save_story(x) and (lambda: None)()
    print("selftest:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="career_coach")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("--json", default="")
    p_add.add_argument("--json-file", default="")
    sub.add_parser("list")
    p_show = sub.add_parser("show"); p_show.add_argument("id")
    p_refine = sub.add_parser("refine"); p_refine.add_argument("id")
    p_refine.add_argument("--field", required=True); p_refine.add_argument("--value", required=True)
    p_gate = sub.add_parser("gate"); p_gate.add_argument("id")
    p_coach = sub.add_parser("coach"); p_coach.add_argument("--text", required=True)
    p_q = sub.add_parser("question"); p_q.add_argument("--competency", default="generic")
    p_s = sub.add_parser("score"); p_s.add_argument("--text", required=True)
    p_s.add_argument("--competency", default="")
    p_m = sub.add_parser("mock"); p_m.add_argument("--competency", default="")
    sub.add_parser("deep-dive")
    sub.add_parser("linkedin")
    sub.add_parser("weekly")
    sub.add_parser("daily-prompt")
    sub.add_parser("weekly-send")
    sub.add_parser("selftest")

    args = parser.parse_args()
    handlers = {
        "add": cmd_add, "list": cmd_list, "show": cmd_show, "refine": cmd_refine,
        "gate": cmd_gate, "coach": cmd_coach, "question": cmd_question, "score": cmd_score,
        "mock": cmd_mock, "deep-dive": cmd_deep_dive, "linkedin": cmd_linkedin,
        "weekly": cmd_weekly, "daily-prompt": cmd_daily_prompt, "weekly-send": cmd_weekly_send,
        "selftest": cmd_selftest,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())