#!/usr/bin/env python3
"""Proactive memory search — scans episodic memory for stuck items,
forgotten decisions, pending todos, and actionable insights.

Runs periodically (cron/scheduler) and sends digest to Telegram.

Usage:
  memory_scanner.py scan [--categories stuck,decision,todo,feedback]
  memory_scanner.py report
  memory_scanner.py notify   # run scan + send to Telegram
  memory_scanner.py ingest   # parse results into facts table
"""
import json, sys, os, sqlite3, argparse, re
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path.home() / ".hermes" / "data" / "unified_memory.db"

# Patterns that indicate actionable items
PATTERNS = {
    "stuck": [
        r"stuck\s+(?:in|on|with)",
        r"crash(?:ing|loop)?",
        r"(?:won't|will not)\s+(?:start|work|connect)",
        r"cycle(?:ing)?",
        r"hamster",
    ],
    "decision": [
        r"need\s+to\s+decide",
        r"should\s+(?:I|we)\s+",
        r"worth\s+(?:it|doing)",
        r"trade.?off",
        r"pros\s+and\s+cons",
    ],
    "todo": [
        r"need\s+to\s+(?:run|fix|check|verify|set up|deploy|restart|investigate)",
        r"should\s+(?:run|fix|check|verify|set up|deploy|restart|investigate)",
        r"todo:",
        r"\btodo\b.*?(?=\n|$)",
        r"action\s+item",
        r"remind",
    ],
    "feedback": [
        r"feedback.*?(?=\n|$)",
        r"(?:good|bad|poor)\s+(?:job|work|execution)",
        r"could\s+be\s+better",
        r"missing\s+feature",
    ],
}

def db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def scan_memory(categories=None, limit_per_cat=10):
    if categories is None:
        categories = list(PATTERNS.keys())

    cats_to_search = [c for c in categories if c in PATTERNS]
    results = {}

    conn = db()
    for cat in cats_to_search:
        patterns = PATTERNS[cat]
        # Use parameterized LIKE to avoid SQL issues
        like_clauses = " OR ".join(["content LIKE ?"] * len(patterns))

        rows = conn.execute(
            f"""SELECT session_id, role, content, timestamp
                FROM messages
                WHERE ({like_clauses})
                ORDER BY timestamp DESC
                LIMIT ?""",
            [f"%{p}%" for p in patterns] + [limit_per_cat]
        ).fetchall()

        # Get role/source labels
        items = []
        for row in rows:
            ts = datetime.fromtimestamp(row["timestamp"], tz=timezone.utc).strftime("%m-%d %H:%M")
            content = (row["content"] or "").strip()[:200]
            # Clean up JSON tool outputs
            try:
                j = json.loads(content)
                if isinstance(j, dict) and "error" in j:
                    continue  # skip tool errors
                if isinstance(j, dict) and "output" in j:
                    content = str(j["output"])[:200]
            except (json.JSONDecodeError, TypeError):
                pass
            items.append({
                "session": row["session_id"][:8],
                "role": row["role"],
                "content": content,
                "ts": ts,
            })
        results[cat] = items

    conn.close()
    return results

def format_report(results):
    lines = ["🧠 **Memory Scanner Report**", f"_Scanned {sum(len(v) for v in results.values())} actionable items_", ""]

    for cat, items in results.items():
        if not items:
            continue
        icon = {"stuck": "🔴", "decision": "🤔", "todo": "📋", "feedback": "💡"}.get(cat, "•")
        lines.append(f"{icon} **{cat.title()}** ({len(items)})")
        for i in items[:5]:
            lines.append(f"  · `{i['ts']}` [{i['session']}] {i['content']}")
        lines.append("")

    if not any(results.values()):
        lines.append("_No actionable items found._")

    return "\n".join(lines)

def send_telegram(report_text, category="infra"):
    """Send report via the bridge /telegram-send endpoint."""
    import urllib.request
    payload = json.dumps({"text": report_text, "category": category}).encode()
    req = urllib.request.Request(
        "http://localhost:9199/telegram-send",
        data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": os.environ.get("BRIDGE_AUTH_KEY", "default-key-change-me")},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"⚠️ Telegram send failed: {e}", file=sys.stderr)
        return None

def main():
    parser = argparse.ArgumentParser(description="Proactive memory scanner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan")
    p.add_argument("--categories", default="stuck,decision,todo,feedback",
                   help="Comma-separated categories to scan")
    p.add_argument("--limit", type=int, default=10, help="Items per category")
    p.set_defaults(func=lambda a: _cmd_scan(a))

    p = sub.add_parser("report")
    p.set_defaults(func=lambda a: _cmd_report(a))

    p = sub.add_parser("notify")
    p.set_defaults(func=lambda a: _cmd_notify(a))

    args = parser.parse_args()
    result = args.func(args)
    if isinstance(result, dict) and "text" in result:
        print(result["text"])
    elif isinstance(result, str):
        print(result)

def _cmd_scan(args):
    cats = args.categories.split(",")
    results = scan_memory(cats, limit_per_cat=args.limit)
    return {"text": format_report(results), "results": results}

def _cmd_report(args):
    results = scan_memory()
    return {"text": format_report(results)}

def _cmd_notify(args):
    results = scan_memory()
    report = format_report(results)
    send_telegram(report, category="infra")
    return {"text": report}

if __name__ == "__main__":
    main()
