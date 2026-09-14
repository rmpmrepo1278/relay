"""__NAME__ — generic watchdog domain script (safe template).

Managed by Jenny. Persistence is a JSON list under ~/.hermes/agents/__NAME__/.
Usage: __NAME__.py check|report|add KIND NAME VALUE [DUE]
"""
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

NAME = __NAME_JSON__
HERMES_HOME = Path(os.path.expanduser("~/.hermes"))
DATA_DIR = HERMES_HOME / "agents" / NAME
DATA_DIR.mkdir(parents=True, exist_ok=True)
STORE = DATA_DIR / "store.json"
ROLE = __ROLE_JSON__
TRIGGERS = __TRIGGERS_JSON__


def load():
    try:
        return json.loads(STORE.read_text())
    except Exception:
        return {"items": [], "meta": {}}


def save(data):
    STORE.write_text(json.dumps(data, indent=2, sort_keys=True))


def check():
    data = load()
    due = []
    today = date.today().isoformat()
    for it in data.get("items", []):
        if it.get("due") and it.get("due") <= today and not it.get("done"):
            due.append(it)
    if due:
        print("%s: %d item(s) due/overdue" % (NAME, len(due)))
        for it in due[:5]:
            print("  - %s %s due %s" % (it.get("kind", "?"), it.get("name", "?"),
                                        it.get("due", "?")))
    else:
        print("%s: check done — 0 due, 0 overdue" % NAME)
    return 0 if not due else 1


def report():
    data = load()
    print("%s (%s)" % (NAME, ROLE))
    print("watchlist triggers: %s" % (", ".join(TRIGGERS) if TRIGGERS else "playbook priorities"))
    items = data.get("items", [])
    print("tracked items: %d" % len(items))
    for it in items[:10]:
        done = "" if it.get("done") else " (open)"
        print("  - %s %s due %s%s" % (it.get("kind", "?"), it.get("name", "?"),
                                      it.get("due", "n/a"), done))


def add_item(kind, name, value, due=""):
    data = load()
    data.setdefault("items", []).append({
        "kind": kind, "name": name, "value": value, "due": due, "done": False,
        "created": datetime.now().isoformat(timespec="seconds"),
    })
    save(data)
    print("added %s: %s (%s)" % (kind, name, value))


def main():
    if len(sys.argv) < 2:
        print("usage: %s.py {check|report|add KIND NAME VALUE [DUE]}" % NAME)
        return 1
    cmd = sys.argv[1]
    if cmd == "check":
        return check()
    if cmd == "report":
        return report()
    if cmd == "add" and len(sys.argv) >= 4:
        add_item(sys.argv[2], sys.argv[3], sys.argv[4],
                 sys.argv[5] if len(sys.argv) > 5 else "")
        return 0
    print("unknown command: [%s]" % cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())