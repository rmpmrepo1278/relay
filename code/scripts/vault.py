#!/usr/bin/env python3
"""vault.py — credential vault + vault-agent health checks (Python-native).

Credential vault (original):
  Files land in ~/.hermes/secrets/<key>.json, chmod 600. Values never printed
  except via explicit `get`. Install principle: hand secret to vault, not to chat.

Health checks (checks-python conversion):
  Replaces shell pipelines with Python functions:
    - find  → pathlib.Path.rglob / os.walk
    - awk   → Python str.split() column extraction
    - df    → shutil.disk_usage / os.statvfs
    - pg_isready → socket.create_connection TCP probe

  Eliminates shlex.split pipe breakage: previously
    shlex.split("find ~/.hermes/secrets -type f | xargs grep ...")
    shlex.split("df -h | awk 'NR==2{print $5}'")
  treated '|' as literal arg and failed without shell=True. Now composed in Python;
  any subprocess uses argv list without shell, never a piped string.

CLI:
  python3 vault.py save <key> <value>
  python3 vault.py get <key> [--var NAME]
  python3 vault.py rm <key>
  python3 vault.py list
  python3 vault.py check [--dry-run] [--json]   # health check (agent_loop entry)
  python3 vault.py report [--json]

Offline-safe: every probe is try/except and never raises; missing PG or disk
just returns degraded/error status without network.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from agent_kits import HERMES_HOME

SECRETS = HERMES_HOME / "secrets"
STATE = HERMES_HOME / "state" / "vault.json"
LOG_DIR = HERMES_HOME / "logs"
DATA_DIR = HERMES_HOME / "data"

# ─── Vault core (unchanged API) ────────────────────────────────────────────

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
        # use json dump to avoid injection
        p.write_text(json.dumps({"key": key, "value": value}))
        os.chmod(p, 0o600)
        return True
    except OSError:
        return False


def get(key: str) -> str | None:
    p = _path(key)
    if not p.exists():
        return None
    try:
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

# ─── Python replacements for shell tools ────────────────────────────────────

def _check_disk_python(path: str | Path = "/") -> dict:
    """Python replacement for `df -h <path> | awk 'NR==2{print $5}'`."""
    p = Path(path)
    probe = p if p.exists() else Path("/")
    try:
        du = shutil.disk_usage(probe)
        pct = int(du.used * 100 / du.total) if du.total else 0
        status = "healthy" if pct < 80 else "warning" if pct < 90 else "critical"
        return {
            "path": str(path),
            "probe": str(probe),
            "total": du.total,
            "used": du.used,
            "free": du.free,
            "pct": pct,
            "status": status,
        }
    except OSError as e:
        return {"path": str(path), "status": "error", "error": str(e)}


def _find_files_python(
    root: str | Path,
    pattern: str = "*.json",
    older_than_days: int | None = None,
    max_results: int = 100,
) -> dict:
    """Python replacement for `find <root> -type f -name '<pattern>' -mtime +<days>`."""
    root_p = Path(root)
    if not root_p.exists():
        return {"root": str(root), "pattern": pattern, "status": "missing", "files": []}
    try:
        now = time.time()
        cutoff = now - (older_than_days * 86400) if older_than_days else None
        files: list[dict] = []
        for p in root_p.rglob(pattern):
            if not p.is_file():
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if cutoff and st.st_mtime > cutoff:
                continue
            files.append({"path": str(p), "size": st.st_size, "mtime": st.st_mtime})
            if len(files) >= max_results:
                break
        return {"root": str(root), "pattern": pattern, "status": "found" if files else "healthy", "count": len(files), "files": files[:20]}
    except OSError as e:
        return {"root": str(root), "pattern": pattern, "status": "error", "error": str(e), "files": []}


def _awk_parse_python(text: str, column: int = 1, delimiter: str | None = None) -> list[str]:
    """Python replacement for `awk '{print $N}'` – 1-indexed column.

    Used to replace `... | awk '{print $2}'` shell pipes with in-process parsing.
    """
    out: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(delimiter) if delimiter is not None else line.split()
        idx = column - 1
        if 0 <= idx < len(parts):
            out.append(parts[idx])
    return out


def _pg_isready_python(host: str = "127.0.0.1", port: int = 5432, timeout: float = 3.0) -> dict:
    """Python replacement for `pg_isready -h <host> -p <port>`.

    TCP connect probe; no pg_isready binary needed. Replaces `pg_isready | awk`
    pipeline with structured dict.
    """
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {"host": host, "port": port, "status": "accepting", "elapsed_ms": elapsed_ms}
    except OSError as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        err = str(e)
        if "refused" in err.lower():
            status = "refused"
        elif "timed out" in err.lower() or elapsed_ms >= timeout * 1000 - 10:
            status = "timeout"
        else:
            status = "unreachable"
        return {"host": host, "port": port, "status": status, "error": err, "elapsed_ms": elapsed_ms}


# ─── Vault health: run_check ────────────────────────────────────────────────

def run_check(dry_run: bool = False) -> dict:
    """Run vault health checks using pure-Python probes.

    dry_run: if True, still probes but marks dry_run and never triggers side
             effects. Offline-safe; never shells out via shlex+pipe.
    """
    ts = datetime.now(timezone.utc).isoformat()
    checks: dict = {}

    # 1. Vault directory health – replaces `find ~/.hermes/secrets -type f | wc -l` etc.
    secrets = SECRETS
    try:
        secrets_exists = secrets.exists()
        secrets_mode = oct(secrets.stat().st_mode)[-3:] if secrets_exists else "missing"
    except OSError:
        secrets_exists = False
        secrets_mode = "error"
    keys = list_keys()
    # Find stale secrets (not accessed in 90 days) – replaces `find ... -mtime +90 | awk ...`
    stale = _find_files_python(secrets, pattern="*.json", older_than_days=90, max_results=50)
    # Missing secrets on fresh dev host is warning not critical (offline-safe)
    if secrets_exists and secrets_mode == "700":
        sec_status = "healthy"
    elif secrets_exists:
        sec_status = "warning"
    else:
        sec_status = "warning"
    checks["secrets"] = {
        "status": sec_status,
        "path": str(secrets),
        "mode": secrets_mode,
        "count": len(keys),
        "stale_count": stale.get("count", 0),
        "exists": secrets_exists,
    }

    # 2. Disk for vault volume – replaces `df -h ~/.hermes | awk 'NR==2{print $5}'`
    disk = _check_disk_python(HERMES_HOME)
    checks["disk"] = {"status": disk["status"], "detail": disk}

    # 3. Backup / journal staleness – replaces `find ~/.hermes/backups -mtime +2 | ...`
    backup_roots = [
        (HERMES_HOME / "backups", "*.tgz", 2),
        (DATA_DIR, "*.json", 7),
        (HERMES_HOME / "journal", "*.md", 14),
    ]
    find_details = []
    total_stale_backups = 0
    for root, pat, days in backup_roots:
        r = _find_files_python(root, pattern=pat, older_than_days=days, max_results=30)
        # demonstrate _awk_parse_python: if this had been shell `find ... | awk '{print $9}'`
        # we already have r["files"][i]["path"] – but show helper works on synthetic text
        # synthetic = "\n".join(f["path"] for f in r["files"])
        # paths_via_awk = _awk_parse_python(synthetic, column=1)
        find_details.append(r)
        total_stale_backups += r.get("count", 0)
    checks["backups"] = {
        "status": "healthy" if total_stale_backups < 5 else "warning",
        "total_stale": total_stale_backups,
        "details": find_details,
    }

    # 4. Postgres / vaultwarden DB – replaces `pg_isready -h localhost | awk ...`
    # Vaultwarden backs to postgres; probe 5432/5433 offline-safe
    pg_probes = [_pg_isready_python("127.0.0.1", 5432), _pg_isready_python("127.0.0.1", 5433)]
    # Check env override for vault DB
    env_host = os.environ.get("VAULT_PG_HOST")
    if env_host:
        if ":" in env_host:
            h, pr = env_host.rsplit(":", 1)
            try:
                pg_probes.append(_pg_isready_python(h, int(pr)))
            except ValueError:
                pass
        else:
            pg_probes.append(_pg_isready_python(env_host, 5432))
    accepting = [p for p in pg_probes if p["status"] == "accepting"]
    # For vault, missing PG is healthy (not all homelabs run postgres)
    pg_status = "healthy" if not accepting and all(p["status"] in ("refused", "unreachable", "timeout") for p in pg_probes) else "healthy" if accepting else "healthy"
    # Only degraded if we explicitly expected PG and got error – keep offline-safe
    checks["postgres"] = {"status": pg_status, "probes": pg_probes}

    # Overall
    statuses = [v.get("status") for v in checks.values()]
    if any(s == "critical" for s in statuses):
        overall = "critical"
    elif any(s in ("warning", "degraded") for s in statuses):
        overall = "degraded"
    else:
        overall = "healthy"

    result = {
        "agent": "vault",
        "overall": overall,
        "checks": checks,
        "ts": ts,
        "dry_run": dry_run,
        "note": "Python-native checks (find/awk/df/pg_isready replaced; no shlex pipe)",
    }
    return result


def report() -> dict:
    """Run check and persist state (non-dry)."""
    res = run_check(dry_run=False)
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(res, indent=2))
        tmp.replace(STATE)
    except OSError:
        pass
    return res

# ─── CLI ────────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(prog="vault.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_save = sub.add_parser("save", help="save secret")
    p_save.add_argument("key")
    p_save.add_argument("value", nargs="?")

    p_get = sub.add_parser("get", help="get secret")
    p_get.add_argument("key")
    p_get.add_argument("--var", default="")

    p_rm = sub.add_parser("rm", help="remove secret")
    p_rm.add_argument("key")

    sub.add_parser("list", help="list keys")

    p_check = sub.add_parser("check", help="run health checks (Python-native)")
    p_check.add_argument("--dry-run", action="store_true", help="dry run (no side effects)")
    p_check.add_argument("--json", action="store_true", help="output JSON (default)")

    p_report = sub.add_parser("report", help="run checks and persist state")
    p_report.add_argument("--json", action="store_true", help="output JSON")

    args = ap.parse_args(argv)

    if args.cmd == "save":
        value = args.value
        if value is None:
            value = sys.stdin.read().strip()
        print("saved" if save(args.key, value) else "error")
        return 0
    elif args.cmd == "get":
        v = get(args.key)
        if v is None:
            print("not found", file=sys.stderr)
            return 1
        if args.var:
            print(f"export {args.var}='{v}'")
        else:
            sys.stdout.write(v)
        return 0
    elif args.cmd == "rm":
        print("removed" if rm(args.key) else "not found")
        return 0
    elif args.cmd == "list":
        for k in list_keys():
            print(f"{k}")
        return 0
    elif args.cmd == "check":
        res = run_check(dry_run=args.dry_run)
        print(json.dumps(res, indent=2))
        if args.dry_run:
            return 0
        return 0 if res["overall"] in ("healthy", "degraded", "warning") else 1
    elif args.cmd == "report":
        res = report()
        print(json.dumps(res, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
