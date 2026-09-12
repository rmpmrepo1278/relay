#!/usr/bin/env python3
"""disaster_recovery.py - Backup state, detect failures, and recover automatically.

If the mind loop dies, the gateway crashes, or databases corrupt,
this module handles automatic recovery and state restoration.
"""

import json
import sqlite3
import shutil
import os
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
BACKUP_DIR = HERMES_HOME / "backups"
RECOVERY_DB = DATA_DIR / "disaster_recovery.db"


def get_db():
    conn = sqlite3.connect(str(RECOVERY_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS backups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        backup_type TEXT NOT NULL,
        backup_path TEXT NOT NULL,
        size_bytes INTEGER DEFAULT 0,
        status TEXT DEFAULT 'success',
        databases_included TEXT DEFAULT '[]',
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS recovery_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        incident_type TEXT NOT NULL,
        severity TEXT DEFAULT 'medium',
        description TEXT NOT NULL,
        recovery_action TEXT NOT NULL,
        result TEXT NOT NULL,
        duration_seconds REAL DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS health_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_name TEXT NOT NULL,
        status TEXT NOT NULL,
        response_time_ms REAL DEFAULT 0,
        details TEXT DEFAULT '{}',
        checked_at TEXT NOT NULL
    )""")
    conn.commit()
    return conn


BACKUP_SOURCES = {
    "databases": [
        HERMES_HOME / "state.db",
        HERMES_HOME / "temporal_kg.db",
        HERMES_HOME / "claudemem.db",
        HERMES_HOME / "kanban.db",
        HERMES_HOME / "shared_facts.db",
        DATA_DIR / "unified_memory.db",
        DATA_DIR / "decisions.db",
        DATA_DIR / "personal.db",
    ],
    "config": [
        HERMES_HOME / "scripts" / "hc_uuids.sh",
    ],
    "state": [
        HERMES_HOME / "state" / "mind_loop.json",
    ],
}



def _ensure_backup_sources_readable():
    """Ensure homelab user can read hermes-owned backup sources (created inside the
    container as uid 10000). Best-effort; runs at backup entry. Idempotent."""
    import subprocess, os
    for src in [HERMES_HOME / "state.db", HERMES_HOME / "state", DATA_DIR / "disaster_recovery.db"]:
        try:
            if src.exists():
                os.chmod(src, 0o644 if src.is_file() else 0o755)
        except PermissionError:
            try:
                subprocess.run(["chmod", "-R", "o+rX", str(src)],
                               check=False, capture_output=True)
            except Exception:
                pass


def create_backup(backup_type="full"):
    """Create a backup of critical data."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"{backup_type}_{now}"
    backup_path.mkdir(parents=True, exist_ok=True)

    included = []
    total_size = 0

    for category, sources in BACKUP_SOURCES.items():
        for src in sources:
            if src.exists():
                dest = backup_path / category / src.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(str(src), str(dest))
                    included.append(str(src.name))
                    total_size += src.stat().st_size
                except Exception:
                    pass

    # Push a copy to OneDrive (nickynrohit@live.com via msonedrive) - best-effort,
    # run BEFORE recording so the status can be persisted.
    push_result = _push_to_onedrive(backup_path)

    # Best-effort migration: ensure onedrive_push column exists (supports pre-existing DBs).
    _ensure_schema_columns()

    conn = get_db()
    now_str = datetime.now().isoformat()
    op_status = json.dumps(push_result)
    conn.execute(
        """INSERT INTO backups (backup_type, backup_path, size_bytes, status, databases_included, onedrive_push, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (backup_type, str(backup_path), total_size, "success",
         json.dumps(included), op_status, now_str),
    )
    conn.commit()
    conn.close()

    return {"path": str(backup_path), "files": len(included), "size": total_size,
            "onedrive_push": push_result}



def _ensure_schema_columns():
    """Idempotent: add onedrive_push column if missing (supports pre-existing DBs)."""
    try:
        conn = get_db()
        cols = {row[1] for row in conn.execute("PRAGMA table_info(backups)").fetchall()}
        if "onedrive_push" not in cols:
            conn.execute("ALTER TABLE backups ADD COLUMN onedrive_push TEXT DEFAULT '{}'")
            conn.commit()
        conn.close()
    except Exception:
        pass


def _push_to_onedrive(backup_path, remote="msonedrive:", dest="HermesBackups"):
    """Best-effort copy of a local backup folder to OneDrive (nickynrohit@live.com).

    Uses rclone. Any failure is swallowed so the local backup still reports
    success; the OneDrive status is returned for operators to inspect.
    """
    import subprocess
    if not backup_path or not Path(backup_path).exists():
        return {"ok": False, "error": "backup path missing"}
    try:
        r = subprocess.run(["rclone", "--version"],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return {"ok": False, "error": "rclone not available"}
    except Exception as e:
        return {"ok": False, "error": "rclone check failed: %s" % e}
    target = f"{remote}{dest}/{Path(backup_path).name}"
    try:
        r = subprocess.run(
            ["rclone", "copy", str(backup_path), target,
             "--verbose", "--transfers", "4"],
            capture_output=True, text=True, timeout=1800,
        )
        if r.returncode == 0:
            return {"ok": True, "target": target}
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["?"]
        return {"ok": False, "error": tail[0][:200]}
    except Exception as e:
        return {"ok": False, "error": "onedrive push failed: %s" % e}

def restore_backup(backup_id=None, backup_path=None):
    """Restore from a backup."""
    conn = get_db()

    if backup_id:
        row = conn.execute("SELECT * FROM backups WHERE id = ?", (backup_id,)).fetchone()
        if not row:
            conn.close()
            return {"error": "Backup not found"}
        backup_path = Path(row["backup_path"])
    elif backup_path:
        backup_path = Path(backup_path)
    else:
        # Use most recent
        row = conn.execute("SELECT * FROM backups ORDER BY created_at DESC LIMIT 1").fetchone()
        if not row:
            conn.close()
            return {"error": "No backups available"}
        backup_path = Path(row["backup_path"])

    if not backup_path.exists():
        conn.close()
        return {"error": f"Backup path not found: {backup_path}"}

    restored = []
    for category in BACKUP_SOURCES:
        cat_dir = backup_path / category
        if cat_dir.exists():
            for src_file in BACKUP_SOURCES[category]:
                backup_file = cat_dir / src_file.name
                if backup_file.exists():
                    try:
                        shutil.copy2(str(backup_file), str(src_file))
                        restored.append(src_file.name)
                    except Exception:
                        pass

    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO recovery_log (incident_type, severity, description, recovery_action, result, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("manual_restore", "info", f"Restored from {backup_path}",
         "restore_backup", f"Restored {len(restored)} files", now),
    )
    conn.commit()
    conn.close()

    return {"restored": len(restored), "files": restored}


def check_service_health():
    """Check health of all hermes services."""
    services = ["hermes-mind-loop", "hermes-gateway", "hermes-scheduler"]
    results = []

    for svc in services:
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "is-active", svc],
                capture_output=True, text=True, timeout=5,
            )
            status = "healthy" if proc.returncode == 0 else "unhealthy"

            # Get uptime
            proc2 = subprocess.run(
                ["systemctl", "--user", "show", svc, "--property=ActiveEnterTimestamp"],
                capture_output=True, text=True, timeout=5,
            )
            uptime = proc2.stdout.strip().split("=", 1)[-1] if proc2.returncode == 0 else "unknown"

            results.append({"service": svc, "status": status, "uptime": uptime})
        except Exception as e:
            results.append({"service": svc, "status": "error", "error": str(e)})

    # Check database integrity
    db_files = list(HERMES_HOME.glob("*.db")) + list(DATA_DIR.glob("*.db"))
    corrupt = []
    for db in db_files:
        try:
            conn = sqlite3.connect(str(db))
            result = conn.execute("PRAGMA quick_check").fetchone()
            conn.close()
            if result[0] != "ok":
                corrupt.append(db.name)
        except Exception:
            corrupt.append(db.name)

    if corrupt:
        results.append({"service": "databases", "status": "corrupt", "files": corrupt})

    # Record checks
    conn = get_db()
    now = datetime.now().isoformat()
    for r in results:
        conn.execute(
            "INSERT INTO health_checks (service_name, status, details, checked_at) VALUES (?, ?, ?, ?)",
            (r["service"], r["status"], json.dumps(r), now),
        )
    conn.commit()
    conn.close()

    return results


def auto_recover():
    """Attempt automatic recovery for known failure modes."""
    conn = get_db()
    now = datetime.now().isoformat()
    recoveries = []

    # Check if services are down
    services = {
        "hermes-mind-loop": "systemctl --user restart hermes-mind-loop",
        "hermes-gateway": "systemctl --user restart hermes-gateway",
        "hermes-scheduler": "systemctl --user restart hermes-scheduler",
    }

    for svc, restart_cmd in services.items():
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "is-active", svc],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode != 0:
                # Service is down, restart it
                subprocess.run(restart_cmd.split(), timeout=10)
                recoveries.append({"service": svc, "action": "restarted"})

                conn.execute(
                    """INSERT INTO recovery_log
                       (incident_type, severity, description, recovery_action, result, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    ("service_down", "high", f"{svc} was down",
                     "auto_restart", "restarted", now),
                )
        except Exception:
            pass

    # Check disk space
    try:
        st = os.statvfs(str(HERMES_HOME))
        free_pct = (st.f_bavail * st.f_frsize) / (st.f_blocks * st.f_frsize) * 100
        if free_pct < 10:
            # Run cleanup
            subprocess.run([str(HERMES_HOME / "scripts" / "rotate_logs.sh")], timeout=30)
            recoveries.append({"action": "disk_cleanup", "free_pct": round(free_pct, 1)})

            conn.execute(
                """INSERT INTO recovery_log
                   (incident_type, severity, description, recovery_action, result, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("low_disk", "high", f"Disk at {free_pct:.1f}% free",
                 "rotate_logs", "cleanup executed", now),
            )
    except Exception:
        pass

    conn.commit()
    conn.close()
    return recoveries


def get_recovery_stats():
    conn = get_db()
    try:
        backups = conn.execute("SELECT COUNT(*) as cnt FROM backups").fetchone()["cnt"]
        last_backup = conn.execute("SELECT created_at FROM backups ORDER BY created_at DESC LIMIT 1").fetchone()
        incidents = conn.execute("SELECT COUNT(*) as cnt FROM recovery_log").fetchone()["cnt"]
        recoveries = conn.execute("SELECT COUNT(*) as cnt FROM recovery_log WHERE result LIKE '%restart%'").fetchone()["cnt"]
        return {
            "total_backups": backups,
            "last_backup": last_backup["created_at"] if last_backup else None,
            "total_incidents": incidents,
            "auto_recoveries": recoveries,
        }
    finally:
        conn.close()


def list_backups():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM backups ORDER BY created_at DESC LIMIT 10").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        print(json.dumps(get_recovery_stats(), indent=2))
    elif cmd == "backup":
        result = create_backup("full")
        push_ok = bool(result.get("onedrive_push", {}).get("ok"))
        report = {
            "status": "success",
            "path": result["path"],
            "files": result["files"],
            "size": result["size"],
            "onedrive_push": result.get("onedrive_push", {}),
            "created_at": datetime.now().isoformat(),
        }
        if report["files"] == 0:
            report["status"] = "error"
            report["note"] = "no source files copied"
        elif not push_ok:
            report["status"] = "warning"
            report["note"] = "local backup ok but OneDrive push failed"
        Path("/home/rohit/.hermes/backup_all_report.json").write_text(json.dumps(report, indent=2))
        if report["status"] != "success":
            try:
                sys.path.insert(0, "/home/rohit/.hermes/scripts")
                from telegram_bridge import send_telegram
                send_telegram("!! Backup issue: %s -- %s (%s)" % (report["status"], report.get("note", ""), report["path"]), priority="critical")
            except Exception:
                pass
        print(f"  Backup: {result["files"]} files, {result["size"]} bytes at {result["path"]}")
    elif cmd == "restore":
        result = restore_backup()
        print(json.dumps(result, indent=2))
    elif cmd == "health":
        for r in check_service_health():
            print(f"  {r['service']}: {r['status']}")
    elif cmd == "recover":
        results = auto_recover()
        for r in results:
            print(f"  {r.get('service', 'system')}: {r['action']}")
    elif cmd == "list":
        for b in list_backups():
            print(f"  [{b['backup_type']}] {b['created_at']}: {b['size_bytes']} bytes")
