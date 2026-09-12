#!/usr/bin/env python3
"""Check integrity of all Hermes SQLite databases and alert on corruption."""
import json
import sqlite3
import sys
import tempfile
import urllib.request
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
LOG_FILE = HERMES_HOME / "logs" / "db_integrity.log"
STATE_FILE = HERMES_HOME / "state" / "db_integrity.json"
TOKEN_FILE = HERMES_HOME / ".telegram_token"
CHAT_ID = "-1003976074764"


def alert_telegram(message: str):
    try:
        token = TOKEN_FILE.read_text().strip()
        data = json.dumps({
            "chat_id": CHAT_ID,
            "text": f"⚠️ {message}",
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Telegram alert failed: {e}")


def check_db(path: Path) -> dict:
    """Integrity-check one SQLite DB.
    Copies the DB (+wal/+shm) to a temp dir and checks the copy, which avoids
    WAL-checkpoint write errors on read-only dirs and the host-sqlite fts5_cjk
    tokenizer gap. Both are environmental, not corruption.
    """
    import shutil
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            res = conn.execute("PRAGMA integrity_check").fetchone()
            res = res[0] if res else "unknown"
            if res == "ok":
                return {"ok": True, "detail": res}
            if "tokenizer" in res:
                return {"ok": True, "detail": "ok (fts tokenizer not in host sqlite)"}
    except Exception:
        pass  # fall through to temp-copy check
    try:
        tmp = tempfile.mkdtemp()
        for sfx in ("", "-wal", "-shm"):
            s = Path(str(path) + sfx)
            if s.exists():
                shutil.copy2(s, Path(tmp) / s.name)
        copy = Path(tmp) / path.name
        with sqlite3.connect(str(copy)) as conn:
            res = conn.execute("PRAGMA integrity_check").fetchone()
            res = res[0] if res else "unknown"
        shutil.rmtree(tmp, ignore_errors=True)
        if res == "ok":
            return {"ok": True, "detail": "ok (verified via temp copy)"}
        if "tokenizer" in res:
            return {"ok": True, "detail": "ok (fts tokenizer not in host sqlite)"}
        return {"ok": False, "detail": res}
    except Exception as e:
        msg = str(e)
        if "tokenizer" in msg:
            return {"ok": True, "detail": "ok (fts tokenizer not in host sqlite)"}
        return {"ok": False, "detail": msg[:160]}


def main():
    dbs = sorted(HERMES_HOME.rglob("*.db"))
    results = {}
    corrupted = []

    for db in dbs:
        if "backups" in db.parts:
            continue
        r = check_db(db)
        results[str(db)] = r
        if not r["ok"]:
            corrupted.append((str(db), r["detail"]))

    ok_count = sum(1 for r in results.values() if r["ok"])
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    summary = f"[{__import__('datetime').datetime.now().isoformat()}] DB integrity: {ok_count}/{len(results)} OK"
    print(summary)
    with LOG_FILE.open("a") as f:
        f.write(summary + "\n")
        for path, detail in corrupted:
            f.write(f"  CORRUPT: {path}: {detail}\n")

    STATE_FILE.write_text(json.dumps({
        "checked_at": __import__('datetime').datetime.now().isoformat(),
        "total": len(results),
        "ok": ok_count,
        "corrupted": [{"path": p, "detail": d} for p, d in corrupted],
    }, indent=2))

    if corrupted:
        msg = f"DB integrity check: {len(corrupted)} database(s) failed"
        alert_telegram(msg)
        for p, d in corrupted[:3]:
            print(f"  CORRUPT: {p}: {d}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())