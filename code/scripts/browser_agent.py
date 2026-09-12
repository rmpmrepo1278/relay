#!/usr/bin/env python3
"""browser_agent.py — computer-use scaffolding for Hermes.

The Instinct/Grok-Bot "browser on a computer of its own" capability, scoped to
what the homelab can run today:

  fetch <url>        -> plain-text snapshot (playwright chromium if available,
                        else urllib + tag stripping) — used by watch jobs
  snapshot <url>     -> same but returns hash (for routine_watcher url_change)
  run-skill <skill>  -> execute a browsing skill via skills_lib (steps can call
                        `browser_agent.py fetch` to bring page text into the skill)

Vision / click / fill automation requires playwright + the local multimodal
Qwen (mmproj). That is gated behind approval via sentinel_gate. See
docs/agent-browser.md for the upgrade path.

CLI:
  python3 browser_agent.py fetch <url>
  python3 browser_agent.py snapshot <url>
  python3 browser_agent.py status
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from html.parser import HTMLParser
from urllib.request import urlopen, Request

_HAVE_PLAYWRIGHT = False
try:
    from playwright.sync_api import sync_playwright  # type: ignore
    _HAVE_PLAYWRIGHT = True
except Exception:
    _HAVE_PLAYWRIGHT = False


class _TextExtract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, d):
        d = d.strip()
        if d:
            self.parts.append(d)


def _strip_html(html: str, limit: int = 6000) -> str:
    try:
        p = _TextExtract()
        p.feed(html)
        text = "\n".join(p.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def fetch(url: str, limit: int = 6000) -> dict:
    if _HAVE_PLAYWRIGHT:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                content = page.content()
                browser.close()
                return {"ok": True, "text": _strip_html(content, limit), "engine": "playwright"}
        except Exception as e:
            return {"ok": False, "error": f"playwright: {str(e)[:120]}", "engine": "playwright"}
    try:
        req = Request(url, headers={"User-Agent": "Hermes-BrowserAgent/0.1"})
        with urlopen(req, timeout=30) as r:
            return {"ok": True, "text": _strip_html(r.read().decode("utf-8", "replace"), limit),
                    "engine": "urllib"}
    except Exception as e:
        return {"ok": False, "error": f"urllib: {str(e)[:120]}", "engine": "urllib"}


def snapshot(url: str) -> dict:
    r = fetch(url, limit=20000)
    if not r["ok"]:
        return r
    return {"ok": True, "sha256": hashlib.sha256(r["text"].encode()).hexdigest(),
            "engine": r["engine"]}


def status() -> dict:
    return {
        "playwright": _HAVE_PLAYWRIGHT,
        "vision_model_ready": False,  # qwen mmproj wiring: next step, see docs
        "advice": ("install: pip install playwright && playwright install chromium"
                   if not _HAVE_PLAYWRIGHT else "playwright ready"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("url")
    s = sub.add_parser("snapshot"); s.add_argument("url")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    if args.cmd == "fetch":
        print(fetch(args.url).get("text", fetch(args.url).get("error", "")))
    elif args.cmd == "snapshot":
        import json
        print(json.dumps(snapshot(args.url)))
    else:
        print(status())
    return 0


if __name__ == "__main__":
    sys.exit(main())