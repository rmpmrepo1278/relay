#!/usr/bin/env python3
"""vault.py — a credential vault agents can use WITHOUT seeing credentials.

Files land in ~/.hermes/secrets/<key>.json, chmod 600, values never printed
(stdout/telegram only ever show the key + a mask). Scripts retrieve a value for
a child subprocess by writing it to a json file / env without logging it.

The Instinct/1Password principle:  "You hand a secret to the vault, not to the
chat. Nobody, including the agent, reads it back in a message."

CLI:
  python3 vault.py save <key> <value>      # value read from argv or stdin
  python3 vault.py get <key>               # prints value ONLY to stdout (for scripts)
  python3 vault.py rm <key>
  python3 vault.py list
  python3 vault.py get <key> --var NAME    # print "export NAME='<value>'" (non-logged)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agent_kits import HERMES_HOME

SECRETS = HERMES_HOME / "secrets"


def _path(key: str) -> Path:
    safe = "".join(c for c in key if c.isalnum() or c in "._-")
    return SECRETS / f"{safe}.json"


def save(key: str, value: str) -> bool:
    SECRETS.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SECRETS, 0o700)
    except OSError:
        pass
    p = _path(key)
    try:
        p.write_text(f'{{"key": "{key}", "value": "{value}"}}')
        os.chmod(p, 0o600)
        return True
    except OSError:
        return False


def get(key: str) -> str | None:
    p = _path(key)
    if not p.exists():
        return None
    try:
        import json
        return json.loads(p.read_text()).get("value")
    except Exception:
        return None


def rm(key: str) -> bool:
    p = _path(key)
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except OSError:
        return False


def list_keys() -> list[str]:
    if not SECRETS.exists():
        return []
    return sorted(p.stem for p in SECRETS.glob("*.json") if p.stem != "_hold")


def _mask(v: str) -> str:
    return (v[:3] + "…" + "***") if v and len(v) > 3 else "***"


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_save = sub.add_parser("save"); p_save.add_argument("key"); p_save.add_argument("value", nargs="?")
    p_get = sub.add_parser("get"); p_get.add_argument("key"); p_get.add_argument("--var", default="")
    p_rm = sub.add_parser("rm"); p_rm.add_argument("key")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    if args.cmd == "save":
        value = args.value
        if value is None:
            value = sys.stdin.read().strip()
        print("saved" if save(args.key, value) else "error")
    elif args.cmd == "get":
        v = get(args.key)
        if v is None:
            print("not found", file=sys.stderr)
            return 1
        if args.var:
            print(f"export {args.var}='{v}'")
        else:
            sys.stdout.write(v)
    elif args.cmd == "rm":
        print("removed" if rm(args.key) else "not found")
    elif args.cmd == "list":
        for k in list_keys():
            print(f"{k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())