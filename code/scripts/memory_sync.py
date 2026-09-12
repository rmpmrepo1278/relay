#!/usr/bin/env python3
"""memory_sync.py — guarded git pull/push of the shared collaborator-memory repo.

Replaces the scheduler's raw `git pull && git push` job so that the known
nightly outage window (11PM-9AM PT) doesn't produce 40+ false failures per day.
Outside the window it retries once on transient DNS failure and exits nonzero
only on genuine conflicts.

CLI:
  python3 memory_sync.py [--push-only] [--verbose]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "collaborator-memory"

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _run(argv: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def guard_skip() -> bool:
    import sys as _sys
    _lib = Path(__file__).resolve().parent / "lib"
    if str(_lib) not in _sys.path:
        _sys.path.insert(0, str(_lib))
    from network_guard import guard
    skip, reason = guard()
    if skip:
        print(f"skip: {reason}")
        return True
    return False


def git_fail(msg: str):
    return f"non-dns git failure: {msg.strip()[:200]}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push-only", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    if guard_skip():
        return 0
    if not (_REPO / ".git").exists():
        print("skip: no git repo at", _REPO)
        return 0

    def do_round() -> tuple[bool, str]:
        """One pull+push attempt. Returns (ok, diagnostic)."""
        if not args.push_only:
            p = _run(["git", "-C", str(_REPO), "pull", "--rebase", "--autostash"])
            low = (p.stdout + p.stderr).lower()
            if p.returncode != 0 and "could not resolve host" in low:
                return False, "dns-fail"     # transient, triggers retry/skip
            if p.returncode != 0:
                return False, git_fail(p.stderr)
        pp = _run(["git", "-C", str(_REPO), "push"])
        low = (pp.stdout + pp.stderr).lower()
        if pp.returncode != 0 and "could not resolve host" in low:
            return False, "dns-fail"
        if pp.returncode != 0:
            return False, git_fail(pp.stderr)
        return True, "ok"

    # attempt 1
    ok, diag = do_round()
    if diag == "dns-fail":
        # brief retry; if still DNS, treat as outage-skip (not a real failure)
        import sys as _sys
        _lib = Path(__file__).resolve().parent / "lib"
        if str(_lib) not in _sys.path:
            _sys.path.insert(0, str(_lib))
        from network_guard import dns_resolves
        if not dns_resolves("github.com"):
            print("skip: DNS still failing, retrying on next cycle")
            return 0
        ok, diag = do_round()
    if not ok:
        print("memory_sync failed:", diag)
        return 1

    if args.verbose:
        print("memory_sync ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())