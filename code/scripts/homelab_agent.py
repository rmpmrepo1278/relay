#!/usr/bin/env python3
"""
homelab_agent.py — Specialist agent for homelab infrastructure administration.

Monitors Docker, systemd, backups, disk, updates; self-heals common issues.
Integrates with Hermes memory, agentbus, Telegram topics, and the agent orchestrator.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

HERMES_HOME = Path.home() / ".hermes"
STATE_DIR = HERMES_HOME / "state"
LOG_DIR = HERMES_HOME / "logs"
DATA_DIR = HERMES_HOME / "data"

STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = STATE_DIR / "homelab_agent.json"
LAST_HEAL_FILE = STATE_DIR / "homelab_last_heal.json"


def _log(msg: str):
    ts = datetime.now(timezone.utc).isoformat()
    with open(LOG_DIR / "homelab_agent.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def _load_state() -> Dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"heal_history": [], "known_issues": {}, "config": {}}


def _save_state(state: Dict):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(STATE_FILE)


def _record_narrative(etype: str, content: str, metadata: Dict | None = None):
    """Record to Hermes narrative memory."""
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        import narrative_memory as _nm
        _nm.store_episode({
            "type": etype,
            "content": content,
            "metadata": metadata or {},
        })
    except Exception:
        pass


def _send_telegram(text: str, thread_id: Optional[int] = None):
    """Send via n8n bridge to the homelab topic."""
    try:
        sys.path.insert(0, str(HERMES_HOME / "scripts"))
        from telegram_bridge import send_telegram
        # Use topic-based thread_id from topic_map if not specified
        effective_thread = thread_id or _get_topic_id()
        send_telegram(text, thread_id=str(effective_thread) if effective_thread else None, parse_mode="Markdown")
    except Exception as e:
        _log(f"Telegram send error: {e}")


def _get_topic_id() -> Optional[int]:
    """Get the homelab forum topic ID from topic_map.json."""
    try:
        tmap = json.loads((HERMES_HOME / "agentbus" / "topic_map.json").read_text())
        # Use "agentbus" topic for homelab, or could create a dedicated "baseplate" topic
        return tmap.get("agentbus")
    except Exception:
        return 7338  # fallback to general thread


def _run_cmd(cmd: str, timeout: int = 30) -> Dict:
    """Run shell command safely."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(e)}


# ─── Health Checks ──────────────────────────────────────────────────────────

def check_docker() -> Dict:
    """Check Docker container health."""
    if not shutil.which("docker"):
        return {"status": "n/a", "error": "no docker CLI in this environment"}
    # Get running containers with status (Health field not always available)
    r = _run_cmd("docker ps --format '{{.Names}}|{{.Status}}'")
    if not r["ok"]:
        return {"status": "error", "error": r["stderr"]}

    containers = []
    unhealthy = []
    for line in r["stdout"].splitlines():
        parts = line.split("|")
        if len(parts) >= 2:
            name, status = parts[0], parts[1]
            containers.append({"name": name, "status": status})
            if "unhealthy" in status.lower() or "dead" in status.lower() or "exited" in status.lower():
                unhealthy.append(name)

    return {
        "status": "degraded" if unhealthy else "healthy",
        "total": len(containers),
        "unhealthy": unhealthy,
        "containers": containers,
    }


def check_systemd(services: List[str] = None) -> Dict:
    """Check systemd user services."""
    if not shutil.which("systemctl"):
        return {"status": "n/a", "error": "no systemctl in this environment"}
    if services is None:
        services = [
            "agentbus", "agentbus-monitor", "hermes-mind-loop",
            "hermes-scheduler", "n8n-bridge", "chatllm-coder30b",
        ]
    r = _run_cmd("systemctl --user is-active " + " ".join(services))
    # is-active returns non-zero if any inactive, but stdout has statuses
    lines = r["stdout"].splitlines()
    statuses = {}
    failed = []
    for line in lines:
        if "=" in line:
            # Not expected format
            continue
        # Format: service_name.service -> active/inactive/failed
        # Actually systemctl --user is-active just prints status per line
        pass

    # Better: use list-units
    r2 = _run_cmd("systemctl --user list-units --type=service --no-legend --plain")
    if not r2["ok"]:
        return {"status": "error", "error": r2["stderr"]}

    failed = []
    for line in r2["stdout"].splitlines():
        parts = line.split()
        if len(parts) >= 4:
            unit = parts[0]
            load = parts[1]
            active = parts[2]
            sub = parts[3]
            if any(s in unit for s in services):
                if active != "active" or sub != "running":
                    failed.append(unit)

    return {
        "status": "degraded" if failed else "healthy",
        "failed": failed,
    }


def check_disk(paths: List[str] = None) -> Dict:
    """Check disk usage."""
    if not shutil.which("df"):
        return {"status": "n/a", "error": "no df in this environment"}
    if paths is None:
        paths = ["/", "/home", "/mnt/usb", "/var/lib/docker"]
    # Never let a nonexistent mount drag a healthy host into "error" — probes
    # run in odd environments (bridge container) with different mounts.
    paths = [p for p in paths if os.path.exists(p)] or ["/"]
    r = _run_cmd("df -h " + " ".join(paths))
    if not r["ok"]:
        return {"status": "error", "error": r["stderr"]}

    issues = []
    for line in r["stdout"].splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) >= 5:
            fs, size, used, avail, pct, mount = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
            pct_num = int(pct.rstrip("%"))
            if pct_num > 85:
                issues.append({"mount": mount, "usage_pct": pct_num, "avail": avail})

    return {
        "status": "warning" if issues else "healthy",
        "issues": issues,
    }


def check_memory() -> Dict:
    """Check memory usage."""
    if not shutil.which("free"):
        return {"status": "n/a", "error": "no free in this environment"}
    r = _run_cmd("free -h")
    if not r["ok"]:
        return {"status": "error", "error": r["stderr"]}

    # Parse free output
    lines = r["stdout"].splitlines()
    mem_line = [l for l in lines if l.startswith("Mem:")][0]
    parts = mem_line.split()
    total, used, free, avail = parts[1], parts[2], parts[3], parts[6] if len(parts) > 6 else parts[3]

    # Also get swap
    swap_line = [l for l in lines if l.startswith("Swap:")][0]
    swap_parts = swap_line.split()
    swap_used = swap_parts[2] if len(swap_parts) > 2 else "0B"

    return {
        "status": "healthy",
        "total": total,
        "used": used,
        "free": free,
        "available": avail,
        "swap_used": swap_used,
    }


def check_backups() -> Dict:
    """Check Kopia backup status (repository lives under root's config — the
    backup jobs run via `sudo -n kopia`; plain `kopia` reports "not connected"
    and we were alerting on that as a config gap)."""
    if not shutil.which("kopia"):
        return {"status": "n/a", "error": "no kopia CLI in this environment"}
    r = _run_cmd("sudo -n kopia repository status 2>&1")
    if "not connected" in r["stdout"].lower() or "not initialized" in r["stdout"].lower():
        return {"status": "not_configured", "note": "Kopia repository not connected"}

    r = _run_cmd("sudo -n kopia snapshot list --json 2>/dev/null | tail -20")
    if not r["ok"] or not r["stdout"]:
        return {"status": "warning", "error": "kopia snapshots not available"}

    try:
        snapshots = []
        for line in r["stdout"].splitlines():
            try:
                snapshots.append(json.loads(line))
            except Exception:
                pass

        if not snapshots:
            return {"status": "warning", "error": "no snapshots found"}

        latest = snapshots[-1]
        latest_time = latest.get("startTime", "")
        age_hours = 0
        if latest_time:
            try:
                dt = datetime.fromisoformat(latest_time.replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            except Exception:
                pass

        status = "healthy"
        if age_hours > 48:
            status = "stale"
        elif age_hours > 24:
            status = "aging"

        return {
            "status": status,
            "latest_snapshot": latest.get("id", "")[:12],
            "age_hours": round(age_hours, 1),
            "total_snapshots": len(snapshots),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def check_updates() -> Dict:
    """Check for available system updates."""
    r = _run_cmd("apt list --upgradable 2>/dev/null | grep -v 'Listing...'")
    if not r["ok"]:
        return {"status": "error", "error": r["stderr"]}

    updates = [l for l in r["stdout"].splitlines() if l.strip()]
    security = [u for u in updates if "security" in u.lower()]

    return {
        "status": "updates_available" if updates else "current",
        "total": len(updates),
        "security": len(security),
        "packages": updates[:10],
    }


def check_agentbus() -> Dict:
    """Check agentbus health. agentbus binds loopback on the HOST only; a
    connection refused from inside a container is an environment artifact, not
    a host outage (the host daemon reports it truthfully)."""
    if not shutil.which("curl"):
        return {"status": "n/a", "error": "no curl in this environment"}
    r = _run_cmd("curl -s http://127.0.0.1:9107/status")
    if not r["ok"] or not r["stdout"]:
        if "refused" in (r.get("stderr", "") or "").lower():
            return {"status": "n/a", "error": "agentbus is host-loopback only; not reachable in this environment"}
        return {"status": "down", "error": "agentbus unreachable"}

    try:
        data = json.loads(r["stdout"])
        return {
            "status": "healthy" if data.get("ok") else "degraded",
            "claims": len(data.get("claims", {})),
            "presence": len(data.get("presence", {})),
            "objectives": len(data.get("objectives", {})),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def run_full_health_check() -> Dict:
    """Run all health checks and return composite status."""
    checks = {
        "docker": check_docker(),
        "systemd": check_systemd(),
        "disk": check_disk(),
        "memory": check_memory(),
        "backups": check_backups(),
        "updates": check_updates(),
        "agentbus": check_agentbus(),
    }

    # Probes that cannot run in this environment ("n/a", e.g. the bridge container
    # has no docker/systemd/df view of the host) must NOT drag the overall into
    # "critical" — they are ignored, not treated as failures.
    real = [c.get("status", "unknown") for c in checks.values() if c.get("status") != "n/a"]

    # Determine overall status
    statuses = real
    if any(s in ("down", "error") for s in statuses):
        overall = "critical"
    elif any(s in ("degraded", "stale", "warning", "aging") for s in statuses):
        overall = "degraded"
    elif any(s == "updates_available" for s in statuses):
        overall = "maintenance_needed"
    elif all(s in ("healthy", "not_configured", "current") for s in statuses):
        overall = "healthy"
    else:
        overall = "healthy"

    # NO auto-send of the health card from here. Callers decide (the 15-min
    # daemon notifies on transitions; the bridge formats its own reply). This
    # function previously sent "🏗️ Homelab Health: CRITICAL" on every non-healthy
    # invocation — which fired inside the bridge container against wrong-env
    # probes and spammed the topic.

    # Record to narrative
    _record_narrative("observation", f"Homelab health check: {overall}", {
        "checks": {k: v.get("status") for k, v in checks.items()},
        "overall": overall,
    })

    return {"overall": overall, "checks": checks, "timestamp": datetime.now(timezone.utc).isoformat()}


# ─── Self-Heal Actions ──────────────────────────────────────────────────────

def heal_docker_unhealthy(container: str) -> Dict:
    """Restart an unhealthy container."""
    _log(f"Healing Docker: restarting {container}")
    r = _run_cmd(f"docker restart {container}")
    if r["ok"]:
        # Verify it's healthy now
        import time
        time.sleep(5)
        r2 = _run_cmd(f"docker inspect --format='{{{{.State.Health.Status}}}}' {container} 2>/dev/null || echo 'no-health'")
        health = r2["stdout"].strip()
        return {"status": "ok" if health == "healthy" else "restarted", "health": health}
    return {"status": "error", "error": r["stderr"]}


def heal_systemd_service(service: str) -> Dict:
    """Restart a failed systemd user service."""
    _log(f"Healing systemd: restarting {service}")
    r = _run_cmd(f"systemctl --user restart {service}")
    if r["ok"]:
        import time
        time.sleep(3)
        r2 = _run_cmd(f"systemctl --user is-active {service}")
        active = r2["stdout"].strip()
        return {"status": "ok" if active == "active" else "restarted", "active": active}
    return {"status": "error", "error": r["stderr"]}


def heal_disk_cleanup() -> Dict:
    """Clean up Docker and apt cache to free space."""
    _log("Healing disk: cleaning caches")
    results = []
    for cmd in [
        "docker system prune -f --volumes 2>/dev/null",
        "apt-get clean",
        "journalctl --vacuum-time=7d",
    ]:
        r = _run_cmd(cmd, timeout=120)
        results.append({"cmd": cmd, "ok": r["ok"]})
    return {"status": "ok" if all(r["ok"] for r in results) else "partial", "results": results}


def heal_agentbus() -> Dict:
    """Restart agentbus if down."""
    _log("Healing agentbus: restarting service")
    r = _run_cmd("systemctl --user restart agentbus")
    if r["ok"]:
        import time
        time.sleep(3)
        r2 = _run_cmd("curl -s http://127.0.0.1:9107/status")
        return {"status": "ok" if r2["ok"] else "restarted"}
    return {"status": "error", "error": r["stderr"]}


def auto_heal(check_result: Dict) -> List[Dict]:
    """Attempt to auto-heal issues found in health check."""
    actions = []
    checks = check_result.get("checks", {})
    state = _load_state()

    # Docker unhealthy containers
    docker = checks.get("docker", {})
    for container in docker.get("unhealthy", []):
        # Rate limit: don't restart same container more than once per hour
        last = state.get("known_issues", {}).get(f"docker:{container}", {}).get("last_heal")
        if last:
            try:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - last_dt).total_seconds() < 3600:
                    continue
            except Exception:
                pass
        result = heal_docker_unhealthy(container)
        actions.append({"action": "heal_docker", "target": container, "result": result})
        if result.get("status") == "ok":
            state.setdefault("known_issues", {})[f"docker:{container}"] = {
                "last_heal": datetime.now(timezone.utc).isoformat(),
                "count": state.get("known_issues", {}).get(f"docker:{container}", {}).get("count", 0) + 1,
            }

    # Systemd failed services
    systemd = checks.get("systemd", {})
    for service in systemd.get("failed", []):
        result = heal_systemd_service(service)
        actions.append({"action": "heal_systemd", "target": service, "result": result})
        if result.get("status") == "ok":
            state.setdefault("known_issues", {})[f"systemd:{service}"] = {
                "last_heal": datetime.now(timezone.utc).isoformat(),
            }

    # Disk space critical
    disk = checks.get("disk", {})
    if any(i.get("usage_pct", 0) > 90 for i in disk.get("issues", [])):
        result = heal_disk_cleanup()
        actions.append({"action": "heal_disk", "result": result})

    # Agentbus down
    agentbus = checks.get("agentbus", {})
    if agentbus.get("status") == "down":
        result = heal_agentbus()
        actions.append({"action": "heal_agentbus", "result": result})
        if result.get("status") == "ok":
            state.setdefault("known_issues", {})["agentbus"] = {
                "last_heal": datetime.now(timezone.utc).isoformat(),
            }

    # Save state
    _save_state(state)

    # Report heal actions
    if actions:
        thread_id = _get_topic_id()
        lines = ["🔧 *Homelab Auto-Heal Actions*"]
        for a in actions:
            target = a.get("target", "")
            res = a.get("result", {})
            lines.append(f"  {a['action']} {target}: *{res.get('status', '?')}*")
        _send_telegram("\n".join(lines), thread_id=thread_id)

        _record_narrative("action", f"Auto-heal: {len(actions)} actions taken", {
            "actions": actions,
        })

    return actions


# ─── Maintenance Actions ────────────────────────────────────────────────────

def apply_updates(security_only: bool = False) -> Dict:
    """Apply system updates."""
    _log("Applying updates" + (" (security only)" if security_only else ""))
    cmd = "apt-get update && apt-get upgrade -y"
    if security_only:
        cmd = "apt-get update && apt-get upgrade -y -t $(lsb_release -cs)-security"
    r = _run_cmd(cmd, timeout=600)
    return {"status": "ok" if r["ok"] else "error", "output": r["stdout"][-500:]}


def pull_docker_images() -> Dict:
    """Pull latest images for running containers."""
    _log("Pulling latest Docker images")
    r = _run_cmd("docker ps --format '{{.Image}}' | sort -u | xargs -r docker pull", timeout=600)
    return {"status": "ok" if r["ok"] else "error", "output": r["stdout"][-500:]}


def verify_backups() -> Dict:
    """Verify Kopia repository integrity."""
    _log("Verifying Kopia backups")
    r = _run_cmd("kopia repository verify 2>/dev/null || echo 'verify failed'", timeout=300)
    return {"status": "ok" if "ERROR" not in r["stdout"] else "error", "output": r["stdout"][-500:]}


# ─── Specialist handler for agent_orchestrator ──────────────────────────────

def homelab_agent(task: Dict) -> Dict:
    """Main handler for homelab specialist."""
    action = task.get("type", task.get("action", ""))
    content = task.get("content", "").lower()
    conf = task.get("confidence", 0.6)

    result = {"assignee": "homelab", "task": task.get("content", ""), "status": "error"}

    try:
        # Map common triggers to actions
        if action == "check" or "check" in content or "health" in content:
            check_result = run_full_health_check()
            result["status"] = "completed"
            result["health"] = check_result
            # Auto-heal if degraded
            if check_result["overall"] in ("critical", "degraded"):
                heal_actions = auto_heal(check_result)
                result["heal_actions"] = heal_actions

        elif action == "heal" or "heal" in content:
            check_result = run_full_health_check()
            heal_actions = auto_heal(check_result)
            result["status"] = "completed"
            result["heal_actions"] = heal_actions

        elif "docker" in content and ("pull" in content or "update" in content):
            result["status"] = "completed"
            result["docker_pull"] = pull_docker_images()

        elif "update" in content and ("system" in content or "apt" in content or "package" in content):
            security = "security" in content
            result["status"] = "completed"
            result["updates"] = apply_updates(security_only=security)

        elif "backup" in content and ("verify" in content or "check" in content):
            result["status"] = "completed"
            result["backup_verify"] = verify_backups()

        elif "disk" in content and "clean" in content:
            result["status"] = "completed"
            result["disk_cleanup"] = heal_disk_cleanup()

        elif "restart" in content:
            # restart <service>
            import re
            match = re.search(r"restart\s+(\S+)", content)
            if match:
                target = match.group(1)
                if target.endswith(".service") or target in ["agentbus", "hermes-mind-loop", "hermes-scheduler", "n8n-bridge"]:
                    result["status"] = "completed"
                    result["restart"] = heal_systemd_service(target)
                else:
                    result["status"] = "completed"
                    result["restart"] = heal_docker_unhealthy(target)
            else:
                result["status"] = "error"
                result["error"] = "specify service or container to restart"

        elif "status" in content or "report" in content:
            check_result = run_full_health_check()
            result["status"] = "completed"
            result["report"] = check_result

        else:
            # Default: full health check
            check_result = run_full_health_check()
            result["status"] = "completed"
            result["health"] = check_result

    except Exception as e:
        result["error"] = str(e)
        result["status"] = "error"
        _log(f"homelab_agent error: {e}")

    _record_narrative("action", f"[homelab] {task.get('content', '')[:200]}", {
        "outcome": result.get("status"),
        "confidence": conf,
    })

    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        action = sys.argv[1]
        if action == "check":
            print(json.dumps(run_full_health_check(), indent=2))
        elif action == "heal":
            check_result = run_full_health_check()
            print(json.dumps(auto_heal(check_result), indent=2))
        elif action == "docker-pull":
            print(json.dumps(pull_docker_images(), indent=2))
        elif action == "verify-backups":
            print(json.dumps(verify_backups(), indent=2))
        elif action == "updates" and len(sys.argv) > 2:
            security = sys.argv[2] == "security"
            print(json.dumps(apply_updates(security_only=security), indent=2))
        elif action == "restart" and len(sys.argv) > 2:
            target = sys.argv[2]
            if target.endswith(".service") or target in ["agentbus", "hermes-mind-loop", "hermes-scheduler", "n8n-bridge"]:
                print(json.dumps(heal_systemd_service(target), indent=2))
            else:
                print(json.dumps(heal_docker_unhealthy(target), indent=2))
    else:
        print(json.dumps(run_full_health_check(), indent=2))