#!/usr/bin/env python3
"""intentional_drift.py - the agent that notices what you repeatedly care about
and crystallizes it into living SOPs (living knowledge), then tells you.

Intentional drift = an *emerging* topic you keep genuinely asking about
(question-style messages) that your model still knows only shallowly with few
recorded interactions. Also fires when personal_model flags an explicit
"may be ready to take action" readiness signal.

Why these bounds: career/infrastructure are deep+heavy-traffic (no SOP yet).
We want SOPs for *new* recurring curiosities you're still learning.
Uses unified_memory.db personal_model (topic_depth + unshared_needs) + messages.
Env: DRIFT_MIN_QUESTIONS (default 2). --dry-run: no writes/paging.
"""
import json, re, sqlite3, uuid, os, sys
from pathlib import Path
from datetime import datetime, timezone

HERMES_HOME = Path.home() / ".hermes"
DB = HERMES_HOME / "data" / "unified_memory.db"
sys.path.insert(0, str(HERMES_HOME / "hermes-agent" / "scripts" / "lib"))
import telegram_send  # type: ignore

MIN_QUESTIONS = int(os.environ.get("DRIFT_MIN_QUESTIONS", "2"))
DRY_RUN = "--dry-run" in sys.argv
SOP_TAG = "auto-sop-via-drift"
KNOWN_DOMAINS = {"career", "infrastructure", "ai_agents", "finance",
                 "health", "habits", "projects", "goals"}

KEYWORD_BAGS = {
    "career": ["job", "career", "resume", "interview", "offer", "hiring", "recruiter",
               "linkedin", "application", "role", "salary", "cv"],
    "infrastructure": ["docker", "container", "compose", "vm", "server", "k8s",
                        "kubernetes", "network", "firewall", "proxy", "backup",
                        "disk", "uptime", "homelab", "raid", "nfs", "nginx"],
    "ai_agents": ["agent", "mcp", "llm", "claude", "model", "prompt", "tool",
                  "kernel", "anthropic", "openai", "gpt"],
    "finance": ["bill", "budget", "cost", "price", "subscription", "invoice", "refund"],
    "health": ["sleep", "exercise", "mood", "stress", "energy", "weight", "headache"],
    "habits": ["habit", "routine", "daily", "tracker", "streak"],
    "goals": ["goal", "okr", "objective", "milestone", "kpi"],
}
QUESTION_MARKERS = re.compile(r"(\?|how |what |why |can i|should i|could you|whats |help me|how do i|how to|want to|need to|ready|why does|why is)")

def _now():
    return datetime.now(timezone.utc).isoformat()

def _load_personal_model(c):
    r = c.execute("SELECT payload FROM personal_model ORDER BY updated DESC LIMIT 1").fetchone()
    return json.loads(r[0]) if r else {}

def _count_genuine_questions(c, keywords):
    if not keywords:
        return 0
    kw_rx = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
    total = 0
    for (txt,) in c.execute("SELECT content FROM messages WHERE role='user' AND content IS NOT NULL"):
        if txt and QUESTION_MARKERS.search(txt) and kw_rx.search(txt):
            total += 1
    return total

def _sop_exists(c, topic):
    return c.execute("SELECT id FROM sops WHERE title LIKE ? LIMIT 1", (f"%{topic}%",)).fetchone()

def run():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    pm = _load_personal_model(c)
    depth = pm.get("topic_depth", {})
    unspoken = pm.get("unspoken_needs", [])
    # readiness signals: "Deep research on career - may be ready to take action"
    signaled = {u["need"].split("-")[0].strip().lower().replace("deep research on ","").strip(): u
                for u in unspoken if "ready to take action" in u.get("need", "")}

    fired = []
    for topic in KNOWN_DOMAINS:
        kw = KEYWORD_BAGS.get(topic, [])
        mentions = _count_genuine_questions(c, kw)
        trow = depth.get(topic, {})
        level = trow.get("depth_level", "deep")
        interactions = trow.get("interactions", 0)

        do_sop, reason = False, ""
        # (a) explicit readiness signal -> crystallize immediately
        if topic in signaled:
            do_sop = True; reason = signaled[topic]["suggested_action"]
        # (b) emerging + shallow + low recorded interactions + you keep asking
        elif level == "shallow" and 2 <= interactions < 60 and mentions >= MIN_QUESTIONS:
            do_sop = True; reason = f"emerging shallow topic: {interactions} recorded interactions + {mentions} question-style mentions"
        # (c) shallow but no interaction recording yet (very new) but asked repeatedly
        elif level == "shallow" and interactions == 0 and mentions >= 3:
            do_sop = True; reason = f"brand-new recurring curiosity: {mentions} questions, no recorded depth"

        if not do_sop:
            continue
        if _sop_exists(c, topic):
            continue

        steps_json = json.dumps([
            {"step": "detect_trigger", "action": "match repeated question pattern in messages"},
            {"step": "gather_evidence", "action": "pull last 10 observations on this topic"},
            {"step": "apply_prior_decision", "action": "reuse decision_register resolution"},
            {"step": "verify_outcome", "action": "record outcome in outcomes table"},
        ])
        now = _now()
        sop_id = f"auto-{uuid.uuid4().hex[:12]}"
        c.execute(
            "INSERT INTO sops (id,title,trigger_desc,steps,tags,created_at,updated_at,"
            "use_count,success_count,fail_count,version,active) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sop_id, f"Crystallized SOP: {topic}",
             f"Triggered by intentional drift - {reason}", steps_json,
             json.dumps([SOP_TAG, topic, "drift"]), now, now, 0, 0, 0, 1, 1),
        )
        if not DRY_RUN:
            c.commit()
        fired.append({"topic": topic, "mentions": mentions, "interactions": interactions,
                      "level": level, "sop_id": sop_id, "reason": reason})

        if not DRY_RUN:
            msg = (
                "📝 I crystallized a new SOP for you: *" + topic + "*\n\n"
                "You keep coming back to this (" + reason + ")."
                "I wrote a reusable playbook so you don't have to re-figure it.\n"
                "SOP id: " + sop_id
            )
            telegram_send.send_telegram(msg, dedup=True)

    c.close()
    return {"fired": fired, "threshold": MIN_QUESTIONS, "dry_run": DRY_RUN}

if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
