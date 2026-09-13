#!/usr/bin/env python3
"""action_loop.py — WS8 Tier 3: confirm-then-act action loop + learning ledger.

A sqlite preference/outcome ledger (~/.hermes/state/pa_ledger.sqlite) plus a
confirm-then-act flow. Proposals come from triggers or manual CLI entry. By
default a proposal is TELEGRAMMED with an action id; it only executes once
confirmed (action_loop.py confirm <id>) or, for explicitly low-risk entries,
immediately at propose time. Every execution records outcome + duration, and
`tune` computes weekly learning (confirm rate, no-response rate, best hours)
and sends a tuning brief to Telegram.

CLI:
  propose --summary "..." [--exec "cmd"] [--confirm auto|0|1]
  confirm <id>                # record confirmation, execute, log outcome
  pref key=value              # upsert a preference
  show [--all]                # recent ledger rows
  tune                        # weekly learning summary -> Telegram

Ledger schema:
  actions(id INTEGER PK, proposed_at, summary, exec_cmd, confirm_required,
          confirmed_at, executed_at, outcome, detail, source)
  preferences(key TEXT PK, value, updated_at, note)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HH = Path.home() / ".hermes"
DB = HH / "state" / "pa_ledger.sqlite"
CONFIRM_WINDOW_H = 6


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB))
    c.execute("""CREATE TABLE IF NOT EXISTS actions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proposed_at TEXT, summary TEXT, exec_cmd TEXT,
        confirm_required INTEGER DEFAULT 1,
        confirmed_at TEXT, executed_at TEXT,
        outcome TEXT, detail TEXT, source TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS preferences(
        key TEXT PRIMARY KEY, value TEXT, updated_at TEXT, note TEXT)""")
    c.commit()
    return c


def send(text: str) -> dict:
    sys.path.insert(0, str(HH / "scripts"))
    from telegram_bridge import send_telegram
    return send_telegram(text)


def propose(summary: str, exec_cmd: str | None, confirm: str, source: str) -> int:
    c = conn()
    req = 0 if confirm in ("0", "no", "immediate") else 1
    cur = c.execute(
        "INSERT INTO actions(proposed_at, summary, exec_cmd, confirm_required, source) VALUES(?,?,?,?,?)",
        (now_iso(), summary, exec_cmd or "", req, source))
    aid = cur.lastrowid
    c.commit()
    if req == 0:
        return execute(aid, c)
    r = send(f"Proposed action #{aid}: {summary}\nReply `action_loop.py confirm {aid}` to run it, or ignore to skip. (window {CONFIRM_WINDOW_H}h)")
    print("proposed:", aid, "send:", r.get("status"))
    return aid


def execute(aid: int, c: sqlite3.Connection | None = None) -> int:
    c = c or conn()
    row = c.execute("SELECT summary, exec_cmd, confirmed_at FROM actions WHERE id=?", (aid,)).fetchone()
    if row is None:
        print("no such action", aid)
        return 1
    summary, exec_cmd, confirmed_at = row
    if not exec_cmd:
        c.execute("UPDATE actions SET confirm_required=0, confirmed_at=?, executed_at=?, outcome=?, detail=? WHERE id=?",
                  (now_iso(), now_iso(), "noop", "no command attached", aid))
        c.commit()
        return 0
    try:
        r = subprocess.run(exec_cmd, shell=True, capture_output=True, text=True, timeout=600)
        ok = r.returncode == 0
        detail = (r.stdout or r.stderr or "").strip()[:400]
        c.execute("UPDATE actions SET confirmed_at=COALESCE(confirmed_at,?), executed_at=?, outcome=?, detail=? WHERE id=?",
                  (now_iso(), now_iso(), "success" if ok else "failure", detail or "(no output)", aid))
    except Exception as ex:
        c.execute("UPDATE actions SET confirmed_at=COALESCE(confirmed_at,?), executed_at=?, outcome=?, detail=? WHERE id=?",
                  (now_iso(), now_iso(), "error", str(ex)[:400], aid))
    c.commit()
    outcome = c.execute("SELECT outcome, detail FROM actions WHERE id=?", (aid,)).fetchone()
    print(f"executed {aid}: {outcome[0]}")
    return 0 if outcome[0] == "success" else 2


def confirm(aid: int) -> int:
    c = conn()
    row = c.execute("SELECT proposed_at, summary, confirmed_at FROM actions WHERE id=?", (aid,)).fetchone()
    if row is None:
        print("no such action", aid)
        return 1
    proposed_at, summary, confirmed_at = row
    if confirmed_at:
        print(f"action {aid} already confirmed")
        return 1
    try:
        prop = datetime.fromisoformat(proposed_at)
        if datetime.now(timezone.utc) - prop > timedelta(hours=CONFIRM_WINDOW_H):
            c.execute("UPDATE actions SET outcome='expired', detail='confirm window elapsed' WHERE id=?", (aid,))
            c.commit()
            print(f"action {aid} confirm window expired; recorded expired")
            return 1
    except Exception:
        pass
    return execute(aid, c)


def pref(key: str, value: str) -> None:
    c = conn()
    c.execute("INSERT INTO preferences(key, value, updated_at, note) VALUES(?,?,?,?) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, note=excluded.note",
              (key, value, now_iso(), "ledger pref"))
    c.commit()
    print(f"pref {key}={value}")


def show(all_rows: bool) -> None:
    c = conn()
    lim = "" if all_rows else " LIMIT 10"
    for r in c.execute("SELECT id, proposed_at, summary, confirm_required, confirmed_at, outcome, source "
                       f"FROM actions ORDER BY id DESC{lim}"):
        print(r)


def tune() -> int:
    c = conn()
    week = now_iso()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    total = c.execute("SELECT COUNT(*) FROM actions WHERE proposed_at>=?", (since,)).fetchone()[0]
    confirmed = c.execute("SELECT COUNT(*) FROM actions WHERE proposed_at>=? AND confirmed_at IS NOT NULL", (since,)).fetchone()[0]
    noresp = c.execute("SELECT COUNT(*) FROM actions WHERE proposed_at>=? AND confirmed_at IS NULL AND executed_at IS NULL",
                       (since,)).fetchone()[0]
    ok = c.execute("SELECT COUNT(*) FROM actions WHERE proposed_at>=? AND outcome='success'", (since,)).fetchone()[0]
    fail = c.execute("SELECT COUNT(*) FROM actions WHERE proposed_at>=? AND outcome IN ('failure','error')", (since,)).fetchone()[0]
    prefs = list(c.execute("SELECT key, value FROM preferences"))
    suggestions = []
    if total > 0 and confirmed / total < 0.5:
        suggestions.append("confirm rate < 50%: raise the preemption bar or shorten proposals")
    if noresp > 3:
        suggestions.append(f"{noresp} proposals got no reply: add a stricter confirm window or auto-skip category")
    if fail > 0:
        suggestions.append(f"{fail} executions failed: review what the loop is allowed to run")
    lines = [
        f"Action loop (7d): {total} proposed, {confirmed} confirmed, {ok} success, {fail} failed, {noresp} no-response.",
        "Preferences: " + (", ".join(f"{k}={v}" for k, v in prefs) or "none"),
    ]
    if suggestions:
        lines.append("Tuning suggestions: " + "; ".join(suggestions))
    text = "Ledger tune\n" + "\n".join(lines)
    r = send(text[:3800])
    print("tune send:", r.get("status"))
    return 0 if r.get("status") in ("ok", "skipped", "deduped") else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="PA action loop + learning ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose")
    p.add_argument("--summary", required=True)
    p.add_argument("--exec", default=None)
    p.add_argument("--confirm", default="auto", help="auto|0|1")
    p.add_argument("--source", default="manual")
    sub.add_parser("confirm").add_argument("id", type=int)
    sub.add_parser("pref").add_argument("kv", help="key=value")
    sub.add_parser("show").add_argument("--all", action="store_true")
    sub.add_parser("tune")
    a = ap.parse_args()
    if a.cmd == "propose":
        propose(a.summary, a.exec, a.confirm, a.source)
    elif a.cmd == "confirm":
        confirm(a.id)
    elif a.cmd == "pref":
        k, v = a.kv.split("=", 1)
        pref(k, v)
    elif a.cmd == "show":
        show(a.all)
    elif a.cmd == "tune":
        return tune()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())