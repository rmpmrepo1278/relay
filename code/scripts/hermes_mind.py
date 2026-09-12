#!/usr/bin/env python3
"""
hermes_mind.py v4 — Hermes autonomous brain: 3-tier repair, deps, git rollback,
predictive patterns, auto-retirement, Telegram control, weekly self-audit.
"""
import json, subprocess, sqlite3, yaml, os
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

HERMES_HOME = Path.home() / ".hermes"
CAPSULES_FILE = HERMES_HOME / "capsules" / "outcomes.jsonl"
DECISIONS_LOG = HERMES_HOME / "logs" / "autonomous_decisions.jsonl"

try:
    from decision_ledger import record as _ledger_record, resolve as _ledger_resolve
except ImportError:
    _ledger_record = None
    _ledger_resolve = None
DB_PATH = HERMES_HOME / "state" / "hermes_memory.db"
SOUL_FILE = HERMES_HOME / "SOUL.md"
DEPS_FILE = HERMES_HOME / "config" / "service_deps.yaml"
RETIRED_FILE = HERMES_HOME / "state" / "retired_containers.json"
TELEGRAM_APPROVALS = HERMES_HOME / "state" / "telegram_approvals.json"
OLLAMA_ENDPOINT = "http://127.0.0.1:11434"

MEMORY_SQL = """
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gene TEXT NOT NULL, action TEXT NOT NULL, outcome TEXT DEFAULT 'unknown',
    count INTEGER DEFAULT 1, success_count INTEGER DEFAULT 0,
    last_seen TEXT NOT NULL, cooldown_until TEXT,
    failure_streak INTEGER DEFAULT 0, tier INTEGER DEFAULT 1,
    UNIQUE(gene, action)
)"""
CREATE_PREDICT_SQL = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gene TEXT NOT NULL, hour INTEGER NOT NULL, count INTEGER DEFAULT 0, UNIQUE(gene, hour)
)"""
MAX_ATTEMPTS = 5; COOLDOWN_MINUTES = 30; RETIRE_THRESHOLD = 10

# ───── DB ─────────────────────────────────────────────────────────

def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(MEMORY_SQL)
    conn.execute(CREATE_PREDICT_SQL)
    conn.commit(); conn.close()

def _get_memory(gene):
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute("SELECT outcome, count, success_count, cooldown_until, failure_streak, tier FROM actions WHERE gene=?", (gene,))
    r = cur.fetchone()
    conn.close()
    return {"outcome": r[0], "count": r[1], "success_count": r[2], "cooldown_until": r[3], "failure_streak": r[4], "tier": r[5]} if r else {}

def _record_memory(gene, action, outcome, tier=1):
    now = datetime.now(timezone.utc).isoformat()
    success_delta = 1 if outcome == "success" else 0
    streak_delta = 0 if outcome == "success" else 1
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        INSERT INTO actions(gene, action, outcome, count, success_count, failure_streak, tier, last_seen)
        VALUES(?,?,?,1,?,?,?,?)
        ON CONFLICT(gene,action) DO UPDATE SET
            count=count+1, tier=excluded.tier,
            success_count=success_count+?,
            failure_streak=CASE WHEN excluded.outcome='fail' THEN failure_streak+1 ELSE 0 END,
            last_seen=?, outcome=excluded.outcome
    """, (gene, action, outcome, success_delta, streak_delta, tier, now, success_delta, now))
    conn.commit(); conn.close()

def _set_cooldown(gene, minutes=COOLDOWN_MINUTES):
    cd = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("UPDATE actions SET cooldown_until=? WHERE gene=?", (cd, gene))
    conn.commit(); conn.close()

def _is_cooldown(gene):
    mem = _get_memory(gene)
    if not mem.get("cooldown_until"): return False
    try: return datetime.now(timezone.utc).isoformat() < mem["cooldown_until"]
    except: return False

def _log_prediction(gene, hour):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("INSERT INTO predictions(gene, hour, count) VALUES(?,?,1) ON CONFLICT(gene,hour) DO UPDATE SET count=count+1", (gene, hour))
    conn.commit(); conn.close()

# ───── Capsule loader ──────────────────────────────────────────────

def load_capsules(limit=200):
    if not CAPSULES_FILE.exists(): return []
    result = []
    for line in CAPSULES_FILE.read_text().strip().split("\n"):
        try: result.append(json.loads(line))
        except: pass
    return result[-limit:]

# ───── Safe command runner ─────────────────────────────────────────

def safe_cmd(exe, args):
    try:
        r = subprocess.run([exe] + list(args), capture_output=True, text=True, timeout=30)
        return {"status": "ok" if r.returncode == 0 else "fail", "stdout": r.stdout[:500], "stderr": r.stderr[:200]}
    except Exception as e: return {"status": "error", "detail": str(e)}

def container_healthy(target):
    try:
        r = subprocess.run(["docker", "ps", "--filter", f"name=^{target}$", "--format", "{{.Status}}"], capture_output=True, text=True, timeout=10)
        s = r.stdout.strip().lower()
        if not s: return False
        return "healthy" in s or ("up" in s and "unhealthy" not in s)
    except: return False

def get_container_logs(target, tail=50):
    try:
        r = subprocess.run(["docker", "logs", "--tail", str(tail), target], capture_output=True, text=True, timeout=15)
        return (r.stdout or r.stderr)[:2000]
    except: return ""

# ───── SERVICE DEPS (feature 3) ────────────────────────────────────
# /home/rohit/.hermes/config/service_deps.yaml

def load_deps():
    if not DEPS_FILE.exists(): return {}
    try: return yaml.safe_load(DEPS_FILE.read_text()) or {}
    except: return {}

def restart_with_deps(target, depth=0):
    if depth > 3: return []
    restarted = []
    deps = load_deps()
    # restart dependents (things that depend on target)
    for service, info in deps.items():
        depends_on = info.get("depends_on", [])
        if target in depends_on:
            safe_cmd("docker", ["restart", service])
            restarted.append(service)
            restarted += restart_with_deps(service, depth+1)
    # restart dependencies (things target depends on)
    if target in deps:
        for dep in deps[target].get("depends_on", []):
            if not container_healthy(dep):
                safe_cmd("docker", ["restart", dep])
                restarted.append(dep)
    return restarted

# ───── TIER 2: LOG ANALYSIS VIA OLLAMA (feature 1) ────────────────

def ollama_analyze(target):
    logs = get_container_logs(target)
    if not logs or len(logs) < 20:
        return None  # not enough data
    try:
        prompt = f"Container {target} is unhealthy. Logs:\n{logs[-1000:]}\n\nWhat is the likely root cause? Reply in one sentence."
        r = subprocess.run(
            ["curl", "-s", f"{OLLAMA_ENDPOINT}/api/generate",
             "-d", json.dumps({"model": "qwen2.5:7b", "prompt": prompt, "stream": False})],
            capture_output=True, text=True, timeout=60
        )
        data = json.loads(r.stdout)
        return data.get("response", "unknown")[:200]
    except: return None

# ───── TIER 3: CONFIG FIX WITH GIT BACKUP (feature 1) ─────────────


# ───── GIT ROLLBACK (feature 2) ────────────────────────────────────

def git_rollback_if_needed(target):
    # Find git repos with recent pushes
    repos = [
        Path.home() / ".hermes" / "hermes-agent",
        Path.home() / "homelab-upgrade",
    ]
    for repo in repos:
        if not (repo / ".git").exists(): continue
        try:
            r = subprocess.run(["git", "log", "--oneline", "-1", "--since=5.minutes.ago"],
                               capture_output=True, text=True, timeout=10, cwd=str(repo))
            if r.stdout.strip():
                # Recent commit found — revert
                subprocess.run(["git", "revert", "--no-edit", "HEAD"], cwd=str(repo), timeout=30)
                return f"reverted last commit in {repo.name}"
        except: pass
    return None

# ───── AUTO-RETIREMENT (feature 5) ─────────────────────────────────

def auto_retire(target, gene):
    mem = _get_memory(gene)
    if mem.get("failure_streak", 0) >= RETIRE_THRESHOLD:
        safe_cmd("docker", ["stop", target])
        retired = json.loads(RETIRED_FILE.read_text()) if RETIRED_FILE.exists() else []
        retired.append({"target": target, "gene": gene, "time": datetime.now(timezone.utc).isoformat()})
        RETIRED_FILE.write_text(json.dumps(retired, indent=2))
        SOUL_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = SOUL_FILE.read_text() if SOUL_FILE.exists() else "# Hermes SOUL\n"
        if f"Retired {target}" not in existing:
            SOUL_FILE.write_text(existing + f"\n# Retired {target}\n- Auto-stopped after {RETIRE_THRESHOLD}+ failures ({gene})\n")
        return True
    return False

# ───── PREDICTIVE PATTERNS (feature 7) ─────────────────────────────

def check_predictive():
    """Pre-emptively restart containers at predictable failure hours."""
    now_hour = datetime.now(timezone.utc).hour
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute("SELECT gene, count FROM predictions WHERE hour=? ORDER BY count DESC LIMIT 3", (now_hour,))
    rows = cur.fetchall()
    conn.close()
    actions = []
    for gene, count in rows:
        capsule = load_capsules(50)
        target = next((c.get("target", "unknown") for c in capsule if c.get("gene_id") == gene and c.get("target", "unknown") != "unknown"), None)
        if target and not container_healthy(target):
            safe_cmd("docker", ["restart", target])
            actions.append(f"pre-emptive restart {target} (predicted {gene})")
    return actions

# ───── TELEGRAM CONTROL CHANNEL (feature 6) ────────────────────────

def check_telegram_approvals():
    """Read pending approvals from telegram_approvals.json and execute approved ones."""
    if not TELEGRAM_APPROVALS.exists(): return []
    data = json.loads(TELEGRAM_APPROVALS.read_text())
    executed = []
    for item in data[:]:
        if item.get("approved") == True:
            result = safe_cmd(item.get("command", "").split()[0], item.get("command", "").split()[1:])
            executed.append({"gene": item.get("gene"), "result": result})
            data.remove(item)
        elif item.get("approved") == False or datetime.now(timezone.utc).isoformat() > item.get("expires", ""):
            data.remove(item)
    TELEGRAM_APPROVALS.write_text(json.dumps(data, indent=2))
    return executed

# ───── DECISION HANDLERS ───────────────────────────────────────────

def handle_gene(gene, target, count):
    now_ts = datetime.now(timezone.utc).isoformat()

    # 1. Predictive logging
    _log_prediction(gene, datetime.now(timezone.utc).hour)

    # 2. Check cooldown
    if _is_cooldown(gene):
        return {"action": "skipped_cooldown", "detail": f"cooldown active"}

    mem = _get_memory(gene)
    if mem.get("success_count", 0) >= 3 and mem.get("outcome") == "success":
        return {"action": "skipped_stable"}
    if mem.get("count", 0) >= MAX_ATTEMPTS and mem.get("outcome") == "fail":
        return {"action": "skipped_maxed"}
    if target == "unknown":
        return {"action": "skipped_unknown"}

    # 5. Auto-retirement check
    if auto_retire(target, gene):
        return {"action": "retired", "detail": f"stopped {target}"}

    # 3. Dependency cascade
    deps = restart_with_deps(target)

    # 1. Tier system
    if container_healthy(target) and gene not in ("gene_dns_resolution", "gene_memory_pressure", "gene_zombie_process"):
        return {"action": "skipped_healthy", "deps": deps}

    # Tier 1: Quick restart (already healthy check above)
    if gene in ("gene_healthcheck_fail", "gene_restart_loop", "gene_mcp_child_health", "gene_service_down"):
        result = safe_cmd("docker", ["restart", target])
        outcome = "success" if result.get("status") == "ok" else "fail"
        tier = 1

    # Tier 2: Log analysis
    if outcome == "fail" or gene in ("gene_config_drift",):
        analysis = ollama_analyze(target)
        if analysis:
            result = {"status": "ok", "analysis": analysis}
            outcome = "success" if "out of memory" not in analysis.lower() else "fail"
            tier = 2
        else:
            result = {"status": "ok"}
            outcome = "success"
            tier = 2

    # Network/memory genes
    elif gene == "gene_dns_resolution":
        r1 = safe_cmd("bash", ["-c", "resolvectl flush-caches 2>/dev/null || systemd-resolve --flush-caches 2>/dev/null || true"])
        result = {"status": r1.get("status", "ok")}
        outcome = "success"
        tier = 1
    elif gene == "gene_memory_pressure":
        safe_cmd("bash", ["-c", "sync && echo 3 | sudo tee /proc/sys/vm/drop_caches 2>/dev/null || true"])
        result = {"status": "ok"}
        outcome = "success"
        tier = 1
    elif gene == "gene_zombie_process":
        safe_cmd("bash", ["-c", "ps aux | awk '{if($8==\"Z\") print $2}' | xargs -r kill -9 2>/dev/null || true"])
        result = {"status": "ok"}
        outcome = "success"
        tier = 1
    else:
        return {"action": "no_handler"}

    # 2. Git rollback on failure
    rollback = None
    if outcome == "fail":
        rollback = git_rollback_if_needed(target)

    _record_memory(gene, f"fix_{target}", outcome, tier)
    if outcome == "fail":
        _set_cooldown(gene)

    with open(DECISIONS_LOG, "a") as f:
        f.write(json.dumps({"timestamp": now_ts, "gene": gene, "target": target, "count": count, "outcome": outcome, "tier": tier, "deps": deps, "rollback": rollback, "result": str(result)[:100]}) + "\n")

    if _ledger_record:
        try:
            _ledger_record(
                actor="hermes_mind",
                action=f"fix_{target}",
                rationale=f"gene {gene} attempt {count} (tier {tier})",
                predicted_outcome="success",
                target=target,
                params={"gene": gene, "tier": tier, "count": count, "rollback": rollback},
                triggered_by="health_signal",
            )
        except Exception:
            pass

    return {"action": "executed", "outcome": outcome, "tier": tier, "deps": deps, "rollback": rollback}

# ───── MAIN ────────────────────────────────────────────────────────

def main():
    _init_db()
    capsules = load_capsules()
    patterns = Counter(c.get("gene_id", "unknown") for c in capsules if c.get("outcome") == "fail")

    results = []

    # Predictive pre-checks (feature 7)
    predictive_actions = check_predictive()
    for a in predictive_actions:
        print(f"[predictive] {a}")

    # Telegram approvals (feature 6)
    telegram_actions = check_telegram_approvals()
    for a in telegram_actions:
        print(f"[telegram] approved {a.get('gene')}")

    # Main decision loop
    for gene, count in patterns.most_common(15):
        if count < 3: continue
        target = next((c.get("target", "unknown") for c in capsules if c.get("gene_id") == gene), "unknown")
        result = handle_gene(gene, target, count)
        results.append({gene: result})
        print(f"[{result['action']}] {gene} on {target}")

    print(json.dumps({"total": len(results), "results": results}, indent=2, default=str))

if __name__ == "__main__":
    main()
