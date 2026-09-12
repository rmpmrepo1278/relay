#!/usr/bin/env python3
"""intent_tracker.py — the Unified Intent Tracker (Hermes' operating brain).

One place that answers: "what is the human working on, what matters most
today, and what should every background agent be aligned with?"

Sources consumed (deduped by title) on `import`:
  - data/personal_tasks.json  (pending tasks)
  - data/commitments.json     (active commitments, via agent_kits.load_commitments)
  - data/goal_engine.db       (the dormant goals table — legacy writer)

New intents arrive via /intent from the Telegram side and via this module's API.

Storage: state/intent_state.json
  { "intents": [ {id,title,category,priority,status,source,created_at,updated_at,
                   done_at,deadline,notes} ],
    "priorities": [id,...],          # today's ordered focus
    "last_updated": iso }

CLI:
  python3 intent_tracker.py add <title> [--category c] [--priority p] [--deadline d]
  python3 intent_tracker.py list [status]
  python3 intent_tracker.py done <id>
  python3 intent_tracker.py drop <id>
  python3 intent_tracker.py reprioritize
  python3 intent_tracker.py import      # pull personal_tasks + commitments + goals
  python3 intent_tracker.py priorities [n]
  python3 intent_tracker.py standup     # morning digest message to home channel
"""
from __future__ import annotations

import argparse
import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from agent_kits import HERMES_HOME, STATE, DATA, read_json, write_json, append_jsonl, now_iso, send

INTENT_PATH = STATE / "intent_state.json"

_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
_CATS = ("career", "research", "admin", "health", "project", "financial", "social", "other")


def _default() -> dict:
    return {"intents": [], "priorities": [], "last_updated": ""}


def _load() -> dict:
    state = read_json(INTENT_PATH, _default())
    if not isinstance(state, dict) or "intents" not in state:
        state = _default()
    state.setdefault("intents", [])
    state.setdefault("priorities", [])
    return state


def _save(state: dict) -> None:
    state["last_updated"] = now_iso()
    INTENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(INTENT_PATH, state)


def _log(rec: dict) -> None:
    append_jsonl(DATA / "intent.log.jsonl", rec)


def _mkid() -> str:
    import itertools
    if not hasattr(_mkid, "_seq"):
        _mkid._seq = itertools.count()
    return "it_" + datetime.now().strftime("%H%M%S") + str(next(_mkid._seq))


def add(title: str, category: str = "other", priority: str = "medium",
        deadline: str = "", source: str = "api") -> dict:
    state = _load()
    title = (title or "").strip()
    if not title:
        return {"ok": False, "error": "empty title"}
    cat = category if category in _CATS else "other"
    prio = priority if priority in _RANK else "medium"
    # dedupe against active intents by title
    for it in state["intents"]:
        if it.get("status") == "active" and it["title"].strip().lower() == title.lower():
            return {"ok": False, "error": f"already an active intent: {it['id']}",
                    "id": it["id"]}
    rec = {
        "id": _mkid(), "title": title, "category": cat, "priority": prio,
        "status": "active", "source": source,
        "created_at": now_iso(), "updated_at": now_iso(), "done_at": None,
        "deadline": str(deadline or ""), "notes": "",
    }
    state["intents"].append(rec)
    _save(state)
    _log({"event": "add", "id": rec["id"], "title": title, "priority": prio, "source": source})
    return {"ok": True, "id": rec["id"], "title": title}


def list(status: str = "active") -> list[dict]:
    state = _load()
    out = [it for it in state["intents"]
           if (it.get("status") or "active") == (status or "active")]
    return sorted(out, key=lambda it: _RANK.get(it.get("priority", "medium"), 9))


def get(it_id: str) -> dict | None:
    for it in _load()["intents"]:
        if it["id"] == it_id:
            return it
    return None


def _set_status(it_id: str, status: str) -> dict:
    state = _load()
    for it in state["intents"]:
        if it["id"] == it_id:
            it["status"] = status
            it["updated_at"] = now_iso()
            if status in ("done", "dropped") and not it.get("done_at"):
                it["done_at"] = now_iso()
            if status == "done":
                state["priorities"] = [p for p in state["priorities"] if p != it_id]
            _save(state)
            _log({"event": status, "id": it_id, "title": it["title"]})
            return {"ok": True, "id": it_id, "status": status}
    return {"ok": False, "error": f"no intent {it_id}"}


def done(it_id: str) -> dict:
    return _set_status(it_id, "done")


def drop(it_id: str) -> dict:
    return _set_status(it_id, "dropped")


def reprioritize() -> int:
    """Order active intents (priority rank, then deadline). Updates state.priorities."""
    state = _load()
    active = [it for it in state["intents"] if (it.get("status") or "active") == "active"]

    def key(it):
        prio = _RANK.get(it.get("priority", "medium"), 9)
        if it.get("deadline"):
            try:
                d = datetime.fromisoformat(it["deadline"].replace("Z", "+00:00"))
                return (prio, d.timestamp())
            except Exception:
                pass
        return (prio, 1 << 62)

    active.sort(key=key)
    state["priorities"] = [it["id"] for it in active]
    _save(state)
    return len(state["priorities"])


def priorities(n: int = 5) -> list[dict]:
    """Return today's top-n ordered active intents (the consultable digest)."""
    reprioritize()
    state = _load()
    idx = {it["id"]: it for it in state["intents"]}
    out = [idx[i] for i in state["priorities"] if i in idx]
    return out[:n]


def import_from_sources() -> dict:
    """One-way merge of external stores → intent_tracker (content-addressed by title)."""
    imported = exited = 0
    seen = {(it["title"].strip().lower()) for it in _load()["intents"] if it.get("status") == "active"}

    # 1) personal_tasks.json pending
    try:
        tasks = read_json(DATA / "personal_tasks.json", {})
        for t in tasks.get("pending", []):
            title = t.get("title") or t.get("description") or ""
            if not title or title.strip().lower() in seen:
                exited += 1
                continue
            r = add(title, category=t.get("type") or "other",
                    priority=t.get("priority") or "medium",
                    deadline=t.get("deadline") or t.get("when") or "",
                    source="personal_tasks")
            if r.get("ok"):
                imported += 1
            seen.add(title.strip().lower())
    except Exception:
        pass

    # 2) commitments.json open
    try:
        from agent_kits import load_commitments
        for c in load_commitments():
            if c.get("status") == "done":
                continue
            text = c.get("text") or ""
            if not text or text.strip().lower() in seen:
                exited += 1
                continue
            r = add(text, category="other", priority="medium",
                    deadline=c.get("due") or "", source="commitments")
            if r.get("ok"):
                imported += 1
            seen.add(text.strip().lower())
    except Exception:
        pass

    # 3) goal_engine.db goals (dormant legacy store — status active)
    try:
        db = Path(DATA) / "goal_engine.db"
        if db.exists():
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                for row in con.execute(
                        "SELECT title, domain, priority, deadline, status FROM goals"
                        " WHERE status NOT IN ('done','completed','dropped','cancelled')"):
                    title, domain, prio, deadline, _ = row
                    if not title or str(title).strip().lower() in seen:
                        exited += 1
                        continue
                    r = add(str(title), category=str(domain or "other"),
                            priority=str(prio or "medium"),
                            deadline=str(deadline or ""), source="goal_engine")
                    if r.get("ok"):
                        imported += 1
                    seen.add(str(title).strip().lower())
            finally:
                con.close()
    except Exception:
        pass

    reprioritize()
    _log({"event": "import", "imported": imported, "already": exited})
    return {"ok": True, "imported": imported, "already_seen": exited}


def standup(n: int = 5) -> str:
    """Morning digest of today's focus, sent to the home channel + returned."""
    items = priorities(n)
    if not items:
        lines = "🎯 <b>Today</b> — no explicit intents yet. Send <b>/intent add …</b> to set focus."
    else:
        badge = {"urgent": "🚨", "high": "🔥", "medium": "·", "low": "·"}
        lines = "🎯 <b>Today's focus</b>:\n" + "\n".join(
            f"{badge.get(i.get('priority','medium'),'·')} <b>{_esc(i['title'])}</b> "
            f"[{_esc(i.get('category','other'))}] <code>{i['id']}</code>"
            for i in items)
        lines += "\n\nSend <b>/intent done &lt;id&gt;</b> when finished."
    send(lines)
    return lines


def _esc(t: str) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add"); p_add.add_argument("title", nargs="+")
    p_add.add_argument("--category", default="other")
    p_add.add_argument("--priority", default="medium")
    p_add.add_argument("--deadline", default="")
    p_lst = sub.add_parser("list"); p_lst.add_argument("status", nargs="?", default="active")
    sub.add_parser("reprioritize")
    sub.add_parser("import")
    sub.add_parser("standup")
    p_prio = sub.add_parser("priorities"); p_prio.add_argument("n", type=int, nargs="?", default=5)
    p_done = sub.add_parser("done"); p_done.add_argument("id")
    p_drop = sub.add_parser("drop"); p_drop.add_argument("id")
    args = ap.parse_args(argv)

    if args.cmd == "add":
        r = add(" ".join(args.title), category=args.category,
                priority=args.priority, deadline=args.deadline, source="cli")
        print(r)
        return 0 if r["ok"] else 1
    if args.cmd == "list":
        for it in list(args.status):
            mark = "🗹" if it.get("status") == "done" else ("✕" if it.get("status") == "dropped" else "◻")
            print(f"{mark} {it['id']} [{it.get('priority'):6}] [{it.get('category')}] {it['title']}")
        return 0
    if args.cmd == "done":
        r = done(args.id); print(r); return 0 if r["ok"] else 1
    if args.cmd == "drop":
        r = drop(args.id); print(r); return 0 if r["ok"] else 1
    if args.cmd == "reprioritize":
        print(f"ordered {reprioritize()} active intents")
        return 0
    if args.cmd == "import":
        r = import_from_sources(); print(r); return 0
    if args.cmd == "standup":
        print("standup sent")
        return 0
    if args.cmd == "priorities":
        for i in priorities(args.n):
            print(f"🔥 {i['title']} [{i['id']}]")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())