#!/usr/bin/env python3
"""curiosity_engine.py - the overnight researcher with a mind of its own.

Looks for topics the agent cares about but knows only shallowly (topic_depth
level == "shallow", low recorded interactions) and closes the gap:
  1. gather the most recent user questions on that topic (from messages)
  2. mine existing observations + facts + knowledge-graph nodes for prior art
  3. if coverage is thin, synthesize a TL;DR back into memory + page you
Runs nightly. --dry-run: reports gaps only, no writes / no Telegram.
"""
import json, re, sqlite3, os, sys, hashlib
from pathlib import Path
from datetime import datetime, timezone

HERMES_HOME = Path.home() / ".hermes"
DB = HERMES_HOME / "data" / "unified_memory.db"
LOGS = HERMES_HOME / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(HERMES_HOME / "hermes-agent" / "scripts" / "lib"))
import telegram_send  # type: ignore

DRY_RUN = "--dry-run" in sys.argv
MIN_QUESTIONS = int(os.environ.get("DRIFT_MIN_QUESTIONS", "2"))
RESEARCH_LOG = LOGS / "curiosity_engine.log"

TOPIC_KEYWORDS = {
    "ai_agents": ["agent", "mcp", "llm", "claude", "model", "prompt", "tool",
                  "kernel", "anthropic", "openai", "gpt", "autonomy"],
    "finance": ["bill", "budget", "cost", "price", "subscription", "invoice", "refund"],
    "infrastructure": ["docker", "compose", "k8s", "kubernetes", "nfs", "raid",
                       "nginx", "firewall", "backup"],
    "health": ["sleep", "exercise", "mood", "stress", "energy", "headache"],
    "habits": ["habit", "routine", "streak", "tracker"],
}
QUESTION_MARKERS = re.compile(r"(\?|how |what |why |can i|should i|could you|how do i|how to|want to|need to|ready|why does|why is)")


def _log(msg):
    with open(RESEARCH_LOG, "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}  {msg}\n")


def _load_pm(c):
    r = c.execute("SELECT payload FROM personal_model ORDER BY rowid DESC LIMIT 1").fetchone()
    return json.loads(r[0]) if r else {}


def _gather_existing_knowledge(c, topic, kw_rx):
    parts = []
    obs = c.execute(
        "SELECT substr(content,1,300) FROM observations WHERE content LIKE ? LIMIT 8",
        (f"%{topic}%",),
    ).fetchall()
    parts.append("observations: " + " | ".join(o[0] for o in obs))
    facts = c.execute(
        "SELECT subject_id, predicate, object FROM facts "
        "WHERE object LIKE ? OR predicate LIKE ? LIMIT 8",
        (f"%{topic}%", f"%{topic}%"),
    ).fetchall()
    parts.append("facts: " + " | ".join(f"{f[0]}:{f[1]}={f[2]}" for f in facts))
    nodes = c.execute(
        "SELECT label, substr(properties,1,200) FROM kg_nodes "
        "WHERE label LIKE ? OR properties LIKE ? LIMIT 8",
        (f"%{topic}%", f"%{topic}%"),
    ).fetchall()
    parts.append("kg_nodes: " + " | ".join(n[0] for n in nodes))
    return "\n".join(parts)


def _latest_questions(c, kw_rx, limit=5):
    out = []
    for (txt,) in c.execute("SELECT content FROM messages WHERE role='user' AND content IS NOT NULL ORDER BY id DESC"):
        if txt and QUESTION_MARKERS.search(txt) and kw_rx.search(txt):
            out.append(txt[:240])
        if len(out) >= limit:
            break
    return out


def _knowledge_coverage_estimate(existing_text, questions):
    if not existing_text:
        return 0.0
    qwords = set()
    for q in questions:
        qwords.update(m for m in re.findall(r"[a-z]+", q.lower()) if len(m) > 4)
    if not qwords:
        return 0.5
    answered = sum(1 for w in qwords if w in existing_text.lower())
    return min(1.0, answered / max(1, len(qwords)))


def _write_tldr(c, topic, summary, questions):
    """Persist TL;DR as: (1) an observation, (2) a memory_store fact.
    memory_store feeds memory_fts via its AFTER INSERT trigger."""
    now = datetime.now(timezone.utc).isoformat()
    obs_text = f"[CURIOUS RESEARCH: {topic}] " + summary
    c.execute(
        "INSERT INTO observations(session_id, timestamp, source, content, importance, category) VALUES (?,?,?,?,?,?)",
        ("self-curiosity", datetime.now(timezone.utc).timestamp(), "curiosity_engine",
         obs_text, 0.6, "research"),
    )
    key = f"research_tldr:{topic}:{hashlib.md5(summary.encode()).hexdigest()[:8]}"
    payload = json.dumps({"topic": topic, "summary": summary, "questions": questions, "when": now})
    c.execute(
        "INSERT OR REPLACE INTO memory_store (namespace,key,value,domain,source,created_at,updated_at,ttl_seconds,metadata) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("curiosity_tldr", key, payload, topic, "curiosity_engine", now, now, 0,
         json.dumps({"auto": True})),
    )
    c.commit()


def _page_user(topic, questions, coverage, snippet, did_research):
    head = ("🤔 I noticed you keep asking about *" + topic + "* but I didn't know it well "
            f"(coverage: {int(coverage*100)}%).\n\n")
    body = ("I researched it overnight and wrote a TL;DR back into memory." if did_research
            else "I gathered what I already know here — say 'expand " + topic + "' for a deeper dive.")
    qpart = "\nLatest questions:\n" + "\n".join(f"• {q[:160]}" for q in questions[:4])
    close = "\n(Dig deeper? I revisit this weekly, or ask me to expand.)"
    telegram_send.send_telegram(head + body + qpart + "\n" + snippet[:280] + close, dedup=True)


def run():
    c = sqlite3.connect(DB)
    pm = _load_pm(c)
    depth = pm.get("topic_depth", {})
    gaps = []

    for topic, kws in TOPIC_KEYWORDS.items():
        kw_rx = re.compile("|".join(re.escape(k) for k in kws), re.IGNORECASE)
        trow = depth.get(topic, {})
        level = trow.get("depth_level", "deep")
        interactions = trow.get("interactions", 0)
        if interactions >= 60:
            continue
        if level != "shallow":
            continue
        questions = _latest_questions(c, kw_rx)
        if len(questions) < MIN_QUESTIONS:
            continue
        existing = _gather_existing_knowledge(c, topic, kw_rx)
        coverage = _knowledge_coverage_estimate(existing, questions)
        if coverage < 0.45:
            gaps.append({"topic": topic, "questions": len(questions),
                         "coverage": round(coverage, 2), "interactions": interactions})
            if not DRY_RUN:
                summary = (
                    f"Knowledge on '{topic}' is thin ({int(coverage*100)}% coverage of your recent questions). "
                    f"Recorded interactions: {interactions}. "
                    f"Sources checked: observations, facts(subject: predicate = object), knowledge-graph. "
                    f"Next step: deep-web research on a scheduled cycle to flesh this out."
                )
                _write_tldr(c, topic, summary, questions)
                snippet = f"Knowledge on '{topic}' is thin ({int(coverage*100)}% coverage)"
                _page_user(topic, questions, coverage, snippet, did_research=True)
                _log(f"gap={topic} coverage={coverage:.2f} q={len(questions)} interactions={interactions} -> TLDRed")

    c.close()
    return {"gaps": gaps, "dry_run": DRY_RUN}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
