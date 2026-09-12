#!/usr/bin/env python3
"""commands.py — Telegram slash-command dispatcher for the agent kits.

Built to be called from telegram_reply_listener.process_update(). Each handler
returns a response string; the listener sends it (HTML) to the originating chat.

Commands:
  /approve <id> | /deny <id> | /always <id>     sentinel gate controls
  /sentinel [pending]                            list gate actions
  /remember <topic> <text>                       append to topical memory
  /forget <topic> <needle>                       remove matching lines
  /memory [list|show <t>|search <q>]
  /topics                                        == /memory list
  /skills                                        list available skills
  /run <skill> [args...]                         run a skill by name
  /brief                                         daily digest on demand
  /vault save <key> <value> | rm <key> | list    credential vault (masked)
  /commitments                                   upcoming + overdue commitments
  /help
"""
from __future__ import annotations

import html as html_mod
from typing import Optional

from agent_kits import DATA, read_json, send

import sentinel_gate as sentinel


def _esc(t: str) -> str:
    return html_mod.escape(str(t), quote=False)[:1500]


def _short(t: str, n: int = 400) -> str:
    t = str(t)
    return t if len(t) <= n else t[:n] + "…"


def _memory_cmd(args: list[str]) -> str:
    import memory_commands as mc
    if not args or args[0] in ("list", "topics"):
        return "📇 Topics:\n" + "\n".join(f"• {_esc(t)}" for t in mc.topic_list()) or "— none yet —"
    if args[0] == "show" and len(args) >= 2:
        r = mc.show(args[1])
        return ("📄 <b>" + _esc(r["name"]) + "</b>\n<pre>" +
                _esc(r["content"][:3000]) + "</pre>" +
                (f"\n… {r['lines'] - 120} more lines" if r.get("truncated") else "")) \
            if r["ok"] else r["error"]
    if args[0] == "search" and len(args) >= 2:
        q = " ".join(args[1:])
        r = mc.search(q)
        lines = "\n".join(f"• {_esc(h['topic'])}:{h['line']} — {_esc(h['text'][:120])}"
                          for h in r.get("hits", [])[:15])
        return f"🔍 “{_esc(q)}” — {r.get('total')} matches\n" + (lines or "none")
    return "usage: /memory list|show <topic>|search <query>"


def _remember_cmd(text: str) -> str:
    import memory_commands as mc
    rest = (text or "").strip()
    parts = rest.split(maxsplit=1)
    if len(parts) < 2:
        return "usage: /remember <topic> <what to remember>"
    r = mc.append(parts[0], parts[1])
    return ("🧠 Remembered in " + _esc(r["name"]) + ":\n<pre>" + _esc(r["line"]) + "</pre>") \
        if r["ok"] else r["error"]


def _forget_cmd(text: str) -> str:
    import memory_commands as mc
    rest = (text or "").strip()
    parts = rest.split(maxsplit=1)
    if len(parts) < 2:
        return "usage: /forget <topic> <matching text to remove>"
    r = mc.forget(parts[0], parts[1])
    return (f"🧽 Removed {r['removed']} line(s) from <b>{_esc(r['name'])}</b>. "
            f"Backup: {r['backup']}") if r["ok"] else r["error"]


def _gate_cmd(action: str, arg: str) -> str:
    arg = (arg or "").strip()
    if action == "list":
        acts = sentinel.list_actions(pending_only=True)
        if not acts:
            return "✅ No actions pending approval."
        return "🧠 Pending:\n" + "\n".join(
            f"• #{_esc(a['id'])} [{_esc(a['kind'])}] {_esc(a['summary'][:100])}"
            for a in acts[:10])
    if not arg:
        return f"usage: /{action} <action-id>"
    r = (sentinel.approve if action == "approve" else
         sentinel.deny if action == "deny" else
         sentinel.always)(arg)
    return ("✅ " + r["message"]) if r["ok"] else ("⚠️ " + r["message"])


def _vault_cmd(text: str) -> str:
    import vault
    parts = (text or "").strip().split(maxsplit=2)
    op = (parts or ["list"])[0]
    if op == "list":
        keys = vault.list_keys()
        return "🔐 Vault keys:\n" + ("\n".join(f"• {_esc(k)}" for k in keys) or "— empty —")
    if op == "save" and len(parts) >= 3:
        ok = vault.save(parts[1], parts[2])
        return ("🔐 Saved (masked). " if ok else "⚠️ save failed") + f"key={_esc(parts[1])}"
    if op == "rm" and len(parts) >= 2:
        ok = vault.rm(parts[1])
        return "🗑 removed" if ok else "not found"
    return "usage: /vault save <key> <secret> | rm <key> | list"


def _skills_cmd() -> str:
    import skills_lib
    skills = skills_lib.list_skills()
    if not skills:
        return "📚 No skills yet in skills/."
    return "📚 Skills:\n" + "\n".join(f"• <b>{_esc(s['name'])}</b> — {_esc(s['description'][:80])}"
                                      for s in skills)


def _run_skill_cmd(text: str) -> str:
    import skills_lib
    parts = (text or "").strip().split()
    if not parts:
        return "usage: /run <skill> [arg=value ...]"
    name = parts[0]
    inputs = {}
    for kv in parts[1:]:
        if "=" in kv:
            k, _, v = kv.partition("=")
            inputs[k.strip()] = v
    r = skills_lib.run(name, inputs)
    if not r.get("ok"):
        return "⚠️ " + r.get("error", "skill run failed")
    return "✅ Skill <b>" + _esc(name) + "</b>\n<pre>" + _esc(r.get("output", "")[:1500]) + "</pre>"


def _brief_cmd() -> str:
    import brief_feed
    r = brief_feed.render()
    return r.get("brief", "could not build brief")


def _commitments_cmd() -> str:
    import commitment_smart
    return commitment_smart.summarize()


def _intent_cmd(text: str) -> str:
    import intent_tracker
    parts = (text or "").strip().split()
    op = (parts or ["list"])[0].lower()
    if op == "add":
        rest = (text or "").strip()[len(op):].strip()
        if not rest:
            return "usage: /intent add <what matters> [--priority high|medium|low] [--category X] [--deadline <iso>]"
        prio = "medium"
        cat = "other"
        deadline = ""
        for flag, dest in (("--priority", "prio"), ("--category", "cat"), ("--deadline", "deadline")):
            if flag in rest.split():
                idx = rest.split().index(flag)
                val = rest.split()[idx + 1] if idx + 1 < len(rest.split()) else ""
                if flag == "--priority": prio = val
                elif flag == "--category": cat = val
                else: deadline = val
        title = " ".join(w for w in rest.split() if not w.startswith("--") and w not in
                         (prio, cat, deadline))
        r = intent_tracker.add(title, category=cat, priority=prio,
                               deadline=deadline, source="telegram")
        if not r.get("ok"):
            return "⚠️ " + r.get("error", "add failed")
        return f"🎯 Intent <b>{_esc(r['title'])}</b> added ([{_esc(r['id'])}])"
    if op == "done" and len(parts) >= 2:
        r = intent_tracker.done(parts[1])
        return ("🗹 Marked done.") if r.get("ok") else ("⚠️ " + r.get("error", "not found"))
    if op == "drop" and len(parts) >= 2:
        r = intent_tracker.drop(parts[1])
        return "✕ Dropped." if r.get("ok") else ("⚠️ " + r.get("error", "not found"))
    # default: list active
    items = intent_tracker.list("active")
    if not items:
        return "🎯 No active intents. <b>/intent add …</b> to set focus."
    lines = "🎯 <b>Active intents</b>:\n" + "\n".join(
        f"{'🔺' if i.get('priority') == 'high' else '·'} <b>{_esc(i['title'])}</b> "
        f"[{_esc(i.get('priority','medium'))}] <code>{_esc(i['id'])}</code>"
        for i in items[:15])
    return lines


def _priorities_cmd() -> str:
    import intent_tracker
    items = intent_tracker.priorities(5)
    if not items:
        return "🎯 No intents yet — <b>/intent add …</b> sets today's focus."
    return "🔥 <b>Today's priorities</b>:\n" + "\n".join(
        f"<b>{_esc(i['title'])}</b> [{_esc(i.get('priority','medium'))}] "
        f"<code>{_esc(i['id'])}</code>" for i in items)


def _health_cmd(text: str) -> str:
    import health_tracker
    parts = (text or "").strip().split()
    if len(parts) == 2 and parts[0].lower() in health_tracker.FIELDS:
        r = health_tracker.log(parts[0], parts[1])
        if r.get("ok"):
            return "✅ Logged " + _esc(r["logged"]["field"]) + "=" + _esc(r["logged"]["value"]) + \
                   "\n\n" + health_tracker.dashboard()
        return "⚠️ " + r.get("error", "log failed")
    return health_tracker.dashboard()


def handle(text: str, update: Optional[dict] = None) -> str:
    """Dispatch one incoming command. Returns the response text (HTML)."""
    if not text or not text.startswith("/"):
        return ""
    body = text[1:].strip()
    cmd, _, arg = body.partition(" ")
    cmd = cmd.lower().split("@")[0]

    if cmd in ("approve", "deny", "always"):
        return _gate_cmd(cmd, arg.strip())
    if cmd == "sentinel" or cmd == "gate":
        return _gate_cmd("list", "")
    if cmd == "remember":
        return _remember_cmd(arg)
    if cmd == "forget":
        return _forget_cmd(arg)
    if cmd == "memory" or cmd in ("topics", "memorytopics"):
        return _memory_cmd(arg.split())
    if cmd == "skills":
        return _skills_cmd()
    if cmd == "run":
        return _run_skill_cmd(arg)
    if cmd == "brief":
        return _brief_cmd()
    if cmd == "vault":
        return _vault_cmd(arg)
    if cmd == "commitments":
        return _commitments_cmd()
    if cmd == "intent":
        return _intent_cmd(arg)
    if cmd == "priorities":
        return _priorities_cmd()
    if cmd == "health":
        return _health_cmd(arg)
    if cmd in ("help", "start", "start@"):
        return (
            "🤖 Hermes Agent Kits\n"
            "/approve <id> · /deny <id> · /always <id> — sentinel action gate\n"
            "/sentinel — pending actions\n"
            "/remember <topic> <text> — add to memory\n"
            "/forget <topic> <text> — remove from memory\n"
            "/memory list | show <t> | search <q>\n"
            "/skills · /run <skill> a=b…\n"
            "/commitments — due/overdue\n"
            "/intent add <what> [--priority high] [--category X] — set focus\n"
            "/intent list | done <id> | drop <id>\n"
            "/priorities — today's top 5\n"
            "/health [sleep H | energy N | mood N | exercise MIN] — trends\n"
            "/brief — today's digest\n"
            "/vault list | save <k> <v> | rm <k>"
        )
    return ""


def is_command(text: str) -> bool:
    return bool(text) and text.startswith("/")


if __name__ == "__main__":
    pass  # imported by the listener; not meant to be run standalone