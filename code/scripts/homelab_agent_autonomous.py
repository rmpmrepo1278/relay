#!/usr/bin/env python3
"""
homelab_agent_autonomous.py — Homelab Infrastructure autonomous agent.

Owns: Docker, systemd, backups, disk, updates, self-heal.
"""

from __future__ import annotations

from autonomous_agent import AutonomousAgent, _log
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import json, subprocess, urllib.request


class HomelabAgent(AutonomousAgent):
    """Homelab Infrastructure autonomous agent."""
    
    def __init__(self):
        super().__init__(
            name="homelab",
            domain="infrastructure",
            topic_id=10026,
            cycle_interval_minutes=15,  # More frequent for infra
        )
    
    # ─── OBSERVE ─────────────────────────────────────────────────────────────
    
    def observe(self) -> dict:
        """Gather infrastructure health signals."""
        signals = {}
        
        # Docker
        signals["docker"] = self._check_docker()
        
        # Systemd
        signals["systemd"] = self._check_systemd()
        
        # Disk
        signals["disk"] = self._check_disk()
        
        # Memory
        signals["memory"] = self._check_memory()
        
        # Backups
        signals["backups"] = self._check_backups()
        
        # Updates
        signals["updates"] = self._check_updates()
        
        # Agentbus
        signals["agentbus"] = self._check_agentbus()
        
        signals["timestamp"] = datetime.now(timezone.utc).isoformat()
        return signals
    
    def _check_docker(self) -> dict:
        try:
            r = subprocess.run(
                "docker ps --format '{{.Names}}|{{.Status}}'",
                shell=True, capture_output=True, text=True, timeout=10
            )
            containers = []
            unhealthy = []
            for line in r.stdout.strip().splitlines():
                parts = line.split("|")
                if len(parts) >= 2:
                    name, status = parts[0], parts[1]
                    containers.append({"name": name, "status": status})
                    if "unhealthy" in status.lower() or "dead" in status.lower() or "exited" in status.lower():
                        unhealthy.append(name)
            return {"status": "degraded" if unhealthy else "healthy", "total": len(containers), "unhealthy": unhealthy, "containers": containers}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _check_systemd(self) -> dict:
        try:
            services = ["agentbus", "agentbus-monitor", "hermes-mind-loop", "hermes-scheduler", "n8n-bridge", "tdai-gateway"]
            r = subprocess.run(f"systemctl --user is-active {' '.join(services)}", shell=True, capture_output=True, text=True, timeout=10)
            failed = [s for s in services if s not in r.stdout]
            return {"status": "degraded" if failed else "healthy", "failed": failed}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _check_disk(self) -> dict:
        try:
            r = subprocess.run("df -h / /home /mnt/usb /var/lib/docker", shell=True, capture_output=True, text=True, timeout=10)
            issues = []
            for line in r.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 5:
                    pct = int(parts[4].rstrip("%"))
                    if pct > 85:
                        issues.append({"mount": parts[5], "usage_pct": pct, "avail": parts[3]})
            return {"status": "warning" if issues else "healthy", "issues": issues}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _check_memory(self) -> dict:
        try:
            r = subprocess.run("free -h", shell=True, capture_output=True, text=True, timeout=5)
            lines = r.stdout.splitlines()
            mem = lines[1].split()
            swap = lines[2].split()
            return {"status": "healthy", "total": mem[1], "used": mem[2], "available": mem[6], "swap_used": swap[2] if len(swap) > 2 else "0"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _check_backups(self) -> dict:
        try:
            r = subprocess.run("kopia repository status 2>&1", shell=True, capture_output=True, text=True, timeout=10)
            if "not connected" in r.stdout.lower():
                return {"status": "not_configured", "note": "Kopia repository not connected"}
            r2 = subprocess.run("kopia snapshot list --json 2>/dev/null | tail -5", shell=True, capture_output=True, text=True, timeout=10)
            snaps = []
            for line in r2.stdout.strip().splitlines():
                try:
                    snaps.append(json.loads(line))
                except Exception:
                    pass
            if not snaps:
                return {"status": "warning", "error": "no snapshots"}
            latest = snaps[-1]
            age_h = 0
            ts = latest.get("startTime", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                except Exception:
                    pass
            status = "healthy"
            if age_h > 48: status = "stale"
            elif age_h > 24: status = "aging"
            return {"status": status, "latest": latest.get("id", "")[:12], "age_h": round(age_h, 1), "total": len(snaps)}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _check_updates(self) -> dict:
        try:
            r = subprocess.run("apt list --upgradable 2>/dev/null | grep -v 'Listing...'", shell=True, capture_output=True, text=True, timeout=30)
            updates = [l for l in r.stdout.splitlines() if l.strip()]
            security = [u for u in updates if "security" in u.lower()]
            return {"status": "updates_available" if updates else "current", "total": len(updates), "security": len(security), "packages": updates[:10]}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _check_agentbus(self) -> dict:
        try:
            with urllib.request.urlopen("http://127.0.0.1:9107/status", timeout=5) as resp:
                data = json.loads(resp.read().decode())
                return {"status": "healthy" if data.get("ok") else "degraded", "claims": len(data.get("claims", {})), "presence": len(data.get("presence", {})), "objectives": len(data.get("objectives", {}))}
        except Exception as e:
            return {"status": "down", "error": str(e)}
    
    # ─── CONNECT ─────────────────────────────────────────────────────────────
    
    def connect(self, signals: dict) -> list:
        insights = []
        
        for name, check in signals.items():
            if name == "timestamp": continue
            status = check.get("status", "?")
            
            if status in ("down", "error", "stale", "aging", "warning", "degraded", "updates_available"):
                severity = "high" if status in ("down", "error") else "medium"
                detail = ""
                if name == "docker" and check.get("unhealthy"):
                    detail = f" — unhealthy: {', '.join(check['unhealthy'])}"
                elif name == "systemd" and check.get("failed"):
                    detail = f" — failed: {', '.join(check['failed'])}"
                elif name == "disk" and check.get("issues"):
                    parts = [f'{i["mount"]} {i["usage_pct"]}%' for i in check["issues"]]
                    detail = " — " + ", ".join(parts)
                elif name == "backups":
                    detail = f" — age: {check.get('age_h', '?')}h"
                elif name == "updates":
                    detail = f" — {check.get('total', 0)} updates ({check.get('security', 0)} security)"
                
                insights.append({
                    "type": "infra_alert",
                    "content": f"Infrastructure {name}: {status}{detail}",
                    "action_suggested": "heal" if status in ("down", "error", "stale", "degraded", "warning") else "maintain",
                    "severity": "high" if status in ("down", "error") else "medium",
                    "domain": name,
                })
        
        return insights
    
    def anticipate(self, signals: dict, insights: list) -> list:
        """Predict maintenance needs."""
        anticipations = []
        
        # If backups aging, anticipate verify
        backups = signals.get("backups", {})
        if backups.get("status") in ("aging", "stale"):
            return [{"type": "preventive", "content": "Backups aging — will verify Kopia snapshots", "action": "verify_backups"}]
        
        # If disk warning, anticipate cleanup
        disk = signals.get("disk", {})
        if any(i.get("usage_pct", 0) > 90 for i in disk.get("issues", [])):
            return [{"type": "preventive", "content": "Disk critical — will clean caches", "action": "clean_disk"}]
        
        # If updates available and it's Sunday, anticipate apply
        now = datetime.now()
        if now.weekday() == 6 and signals.get("updates", {}).get("status") == "updates_available":
            return [{"type": "scheduled", "content": "Sunday maintenance window — will apply updates", "action": "apply_updates"}]
        
        return []
    
    def plan(self, signals: dict, insights: list, anticipations: list) -> list:
        plans = []
        
        # Handle insights
        for insight in insights:
            severity = insight.get("severity", "medium")
            priority = {"critical": 10, "high": 8, "medium": 5, "low": 3}.get(insight.get("severity"), 5)
            
            if insight.get("action_suggested") == "heal":
                plans.append({
                    "action": "heal",
                    "domain": insight.get("domain"),
                    "priority": priority,
                    "confidence": 0.8,
                    "source_insight": insight.get("content", "")[:80],
                })
            elif insight.get("action_suggested") == "maintain":
                plans.append({
                    "action": "notify",
                    "content": insight.get("content"),
                    "priority": priority,
                    "confidence": 0.6,
                })
        
        # Handle anticipations
        for ant in anticipations:
            plans.append({
                "action": ant.get("action"),
                "priority": 7,
                "confidence": 0.7,
            })
        
        return plans
    
    def act(self, plans: list, signals: dict) -> list:
        results = []
        
        for plan in plans:
            action = plan.get("action")
            try:
                if action == "heal":
                    domain = plan.get("domain")
                    result = self._heal_domain(domain, signals)
                    results.append({"action": "heal", "domain": domain, "status": "ok", "detail": result})
                
                elif action == "verify_backups":
                    results.append({"action": "verify_backups", "status": "ok", "detail": self._verify_backups()})
                
                elif action == "clean_disk":
                    results.append({"action": "clean_disk", "status": "ok", "detail": self._clean_disk()})
                
                elif action == "apply_updates":
                    security_only = False
                    results.append({"action": "apply_updates", "status": "ok", "detail": self._apply_updates(security_only)})
                
                elif action == "notify":
                    self.send_to_own_topic(f"⚠️ {plan.get('content')}")
                    results.append({"action": "notify", "status": "ok"})
                
                else:
                    results.append({"action": plan.get("action"), "status": "unknown"})
                    
            except Exception as e:
                results.append({"action": plan.get("action"), "status": "error", "error": str(e)})
        
        return results
    
    def _heal_domain(self, domain: str, signals: dict) -> dict:
        if domain == "docker":
            check = signals.get("docker", {})
            healed = []
            for container in check.get("unhealthy", []):
                result = subprocess.run(f"docker restart {container}", shell=True, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    healed.append(container)
            return {"healed": healed}
        
        elif domain == "systemd":
            check = signals.get("systemd", {})
            healed = []
            for service in check.get("failed", []):
                result = subprocess.run(f"systemctl --user restart {service}", shell=True, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    healed.append(service)
            return {"healed": healed}
        
        elif domain == "agentbus":
            result = subprocess.run("systemctl --user restart agentbus", shell=True, capture_output=True, text=True, timeout=30)
            return {"restarted": result.returncode == 0}
        
        return {"error": f"Unknown domain: {domain}"}
    
    def _verify_backups(self) -> dict:
        result = subprocess.run("kopia repository verify 2>/dev/null || echo 'verify failed'", shell=True, capture_output=True, text=True, timeout=300)
        return {"ok": "ERROR" not in result.stdout}
    
    def _clean_disk(self) -> dict:
        results = []
        for cmd in ["docker system prune -f --volumes 2>/dev/null", "apt-get clean", "journalctl --vacuum-time=7d"]:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            results.append({"cmd": cmd, "ok": r.returncode == 0})
        return {"ok": all(r["ok"] for r in results), "results": results}
    
    def _apply_updates(self, security_only: bool = False) -> dict:
        cmd = "apt-get update && apt-get upgrade -y"
        if security_only:
            cmd = "apt-get update && apt-get upgrade -y -t $(lsb_release -cs)-security"
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
        return {"ok": r.returncode == 0, "output": r.stdout[-500:]}
    
    def reflect(self, signals: dict, insights: list, plans: list, results: list) -> dict:
        reflection = super().reflect(signals, insights, plans, results)
        
        # Track health trends
        health = signals.get("docker", {}).get("status")
        if health:
            hist = self.state.get("health_history", [])
            hist.append({"ts": datetime.now(timezone.utc).isoformat(), "docker_status": health})
            self.state["health_history"] = hist[-100:]
        
        return reflection


if __name__ == "__main__":
    import sys
    agent = HomelabAgent()
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        agent.run_daemon()
    else:
        import json
        print(json.dumps(agent.run_cycle(), indent=2))